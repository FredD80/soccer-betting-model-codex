"""
Cross-provider team name resolution.

Priority:
    1. Exact match against Team.name (league-scoped).
    2. Case-insensitive TeamAlias match (source-scoped).
    3. Fuzzy match via difflib with a high cutoff (>= 0.85). A successful
       fuzzy match is persisted as a new TeamAlias so subsequent lookups
       are deterministic.

Returns None if no match clears the fuzzy threshold — caller decides
whether to insert a new Team or skip the row.
"""
import re
import unicodedata
from difflib import SequenceMatcher

from app.db.models import Team, TeamAlias

FUZZY_THRESHOLD = 0.85
NORMALIZED_FUZZY_THRESHOLD = 0.76
NORMALIZED_STOPWORDS = {
    "ac",
    "afc",
    "as",
    "association",
    "athletic",
    "athletique",
    "cf",
    "club",
    "de",
    "fc",
    "foot",
    "football",
    "hsc",
    "olympique",
    "sc",
    "sporting",
    "stade",
    "the",
}
NORMALIZED_TOKEN_SYNONYMS = {
    "koeln": "cologne",
    "koln": "cologne",
}


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def _normalized_name(value: str) -> str:
    folded = re.sub(r"[^a-z0-9]+", " ", _fold(value)).strip()
    if not folded:
        return ""
    tokens = [
        NORMALIZED_TOKEN_SYNONYMS.get(token, token)
        for token in folded.split()
        if token not in NORMALIZED_STOPWORDS
    ]
    if not tokens:
        tokens = [NORMALIZED_TOKEN_SYNONYMS.get(token, token) for token in folded.split()]
    return " ".join(tokens)


def _persist_alias(session, team_id: int, raw_name: str, source: str) -> None:
    existing = (
        session.query(TeamAlias)
        .filter(TeamAlias.team_id == team_id)
        .filter(TeamAlias.source == source)
        .filter(TeamAlias.alias.ilike(raw_name))
        .first()
    )
    if existing is None:
        session.add(TeamAlias(team_id=team_id, alias=raw_name, source=source))


def resolve_team(
    session, league_id: int, raw_name: str, source: str
) -> Team | None:
    """Return the Team row for `raw_name` or None if no confident match."""
    if not raw_name:
        return None
    raw_name = raw_name.strip()

    exact = (
        session.query(Team)
        .filter(Team.league_id == league_id)
        .filter(Team.name.ilike(raw_name))
        .first()
    )
    if exact is not None:
        return exact

    alias = (
        session.query(TeamAlias)
        .join(Team, TeamAlias.team_id == Team.id)
        .filter(Team.league_id == league_id)
        .filter(TeamAlias.source == source)
        .filter(TeamAlias.alias.ilike(raw_name))
        .first()
    )
    if alias is not None:
        return session.query(Team).filter_by(id=alias.team_id).first()

    candidates = session.query(Team).filter(Team.league_id == league_id).all()
    raw_normalized = _normalized_name(raw_name)

    normalized_exact = [team for team in candidates if _normalized_name(team.name) == raw_normalized]
    if len(normalized_exact) == 1:
        _persist_alias(session, normalized_exact[0].id, raw_name, source)
        return normalized_exact[0]

    collapsed = [
        team
        for team in candidates
        if raw_normalized
        and _normalized_name(team.name)
        and (
            raw_normalized in _normalized_name(team.name)
            or _normalized_name(team.name) in raw_normalized
        )
    ]
    if len(collapsed) == 1:
        _persist_alias(session, collapsed[0].id, raw_name, source)
        return collapsed[0]

    best, best_score = None, 0.0
    best_normalized, best_normalized_score = None, 0.0
    for team in candidates:
        score = _ratio(raw_name, team.name)
        if score > best_score:
            best, best_score = team, score
        normalized_score = _ratio(raw_normalized, _normalized_name(team.name))
        if normalized_score > best_normalized_score:
            best_normalized, best_normalized_score = team, normalized_score

    if best is not None and best_score >= FUZZY_THRESHOLD:
        _persist_alias(session, best.id, raw_name, source)
        return best

    if best_normalized is not None and best_normalized_score >= NORMALIZED_FUZZY_THRESHOLD:
        _persist_alias(session, best_normalized.id, raw_name, source)
        return best_normalized

    return None
