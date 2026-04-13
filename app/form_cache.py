import logging
from datetime import datetime, timezone
from app.db.models import Fixture, FormCache, Result, Team

logger = logging.getLogger(__name__)


def _red_card_weight(red_card_minute: int | None) -> float:
    """Return the result weight based on when the red card occurred.
    None  → 1.0  (no red card — full weight)
    <  60 → 0.25 (early red card — result likely distorted)
    >= 60 → 0.75 (late red card — partial distortion)
    """
    if red_card_minute is None:
        return 1.0
    return 0.25 if red_card_minute < 60 else 0.75


class FormCacheBuilder:
    def __init__(self, session, lookback: int = 5):
        self.session = session
        self.lookback = lookback

    def build_all(self) -> int:
        """Rebuild form cache for all teams. Returns count of cache rows written."""
        teams = self.session.query(Team).all()
        count = 0
        for team in teams:
            for is_home in (True, False):
                if self._build_team_form(team.id, is_home):
                    count += 1
        self.session.commit()
        return count

    def build_for_fixture(self, fixture_id: int):
        """Rebuild form cache for both teams in a specific fixture."""
        fixture = self.session.query(Fixture).filter_by(id=fixture_id).first()
        if not fixture:
            return
        self._build_team_form(fixture.home_team_id, is_home=True)
        self._build_team_form(fixture.away_team_id, is_home=False)
        self.session.commit()

    def _build_team_form(self, team_id: int, is_home: bool) -> bool:
        rows = self._fetch_last_n(team_id, is_home)
        if not rows:
            return False

        total_weight = 0.0
        weighted_scored = 0.0
        weighted_conceded = 0.0
        cover_weight = 0.0
        ou_weight_15 = 0.0
        ou_weight_25 = 0.0
        ou_weight_35 = 0.0

        for result, fixture in rows:
            w = _red_card_weight(result.red_card_minute)
            scored = result.home_score if is_home else result.away_score
            conceded = result.away_score if is_home else result.home_score
            total = result.total_goals or 0

            total_weight += w
            weighted_scored += scored * w
            weighted_conceded += conceded * w
            if scored > conceded:
                cover_weight += w
            if total > 1.5:
                ou_weight_15 += w
            if total > 2.5:
                ou_weight_25 += w
            if total > 3.5:
                ou_weight_35 += w

        if total_weight == 0:
            return False

        kwargs = dict(
            goals_scored_avg=weighted_scored / total_weight,
            goals_conceded_avg=weighted_conceded / total_weight,
            spread_cover_rate=cover_weight / total_weight,
            ou_hit_rate_15=ou_weight_15 / total_weight,
            ou_hit_rate_25=ou_weight_25 / total_weight,
            ou_hit_rate_35=ou_weight_35 / total_weight,
            matches_count=len(rows),
            updated_at=datetime.now(timezone.utc),
        )
        existing = (self.session.query(FormCache)
                    .filter_by(team_id=team_id, is_home=is_home).first())
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
        else:
            self.session.add(FormCache(team_id=team_id, is_home=is_home, **kwargs))
        return True

    def populate_xg_from_understat(self, understat_matches: list[dict], team_name: str, team_id: int, is_home: bool) -> None:
        """Update form_cache xG fields from a list of Understat match dicts."""
        side = "h" if is_home else "a"
        opp = "a" if is_home else "h"
        xg_scored = [float(m[side]["xG"]) for m in understat_matches if m[side]["title"] == team_name]
        xg_conceded = [float(m[opp]["xG"]) for m in understat_matches if m[side]["title"] == team_name]
        if not xg_scored:
            return
        lookback = xg_scored[-self.lookback:]
        lookback_c = xg_conceded[-self.lookback:]
        cache = (self.session.query(FormCache)
                 .filter_by(team_id=team_id, is_home=is_home).first())
        if cache:
            cache.xg_scored_avg = sum(lookback) / len(lookback)
            cache.xg_conceded_avg = sum(lookback_c) / len(lookback_c)
            self.session.commit()

    def _fetch_last_n(self, team_id: int, is_home: bool) -> list:
        team_filter = (
            Fixture.home_team_id == team_id if is_home
            else Fixture.away_team_id == team_id
        )
        return (
            self.session.query(Result, Fixture)
            .join(Fixture, Result.fixture_id == Fixture.id)
            .filter(team_filter)
            .filter(Result.home_score.isnot(None))
            .order_by(Fixture.kickoff_at.desc())
            .limit(self.lookback)
            .all()
        )
