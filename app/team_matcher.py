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
from difflib import SequenceMatcher

from app.db.models import Team, TeamAlias

FUZZY_THRESHOLD = 0.85


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def resolve_team(
    session, league_id: int, raw_name: str, source: str
) -> Team | None:
    """Return the Team row for `raw_name` or None if no confident match."""
    if not raw_name:
        return None

    exact = (
        session.query(Team)
        .filter(Team.league_id == league_id)
        .filter(Team.name == raw_name)
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
    best, best_score = None, 0.0
    for team in candidates:
        score = _ratio(raw_name, team.name)
        if score > best_score:
            best, best_score = team, score

    if best is not None and best_score >= FUZZY_THRESHOLD:
        session.add(TeamAlias(team_id=best.id, alias=raw_name, source=source))
        return best

    return None
