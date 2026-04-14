import logging
from datetime import datetime, timezone, timedelta
from app.db.models import Fixture, FormCache, OddsSnapshot, SpreadPrediction, League
from app.dixon_coles import build_score_matrix, spread_cover_dc
from app.league_calibration import get_league_params
from app.market_blend import blend, get_weights
from app.edge_tiers import edge_tier, kelly_fraction
from app.steam_resistance import steam_move_pct, apply_steam

logger = logging.getLogger(__name__)

GOAL_LINES = [-1.5, -1.0, -0.5, 0.5, 1.0, 1.5]  # fallback when fixture has no offered lines
LEAGUE_AVG_GOALS = 1.5  # normalisation constant for attack × defense formula


def _implied_prob(decimal_odds: float | None) -> float | None:
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    return 1.0 / decimal_odds


class SpreadPredictor:
    def __init__(self, session, lead_hours: int | None = None, ml_enabled: bool = False):
        self.session = session
        self._lead_hours = lead_hours
        self._ml = None
        if ml_enabled:
            from app.ml_lambda import MLLambdaPredictor
            self._ml = MLLambdaPredictor(session)

    def run(self, model_id: int):
        upcoming = self._get_upcoming_fixtures()
        if upcoming:
            self.session.query(SpreadPrediction).filter(
                SpreadPrediction.model_id == model_id,
                SpreadPrediction.fixture_id.in_([f.id for f in upcoming]),
            ).delete(synchronize_session=False)
        for fixture in upcoming:
            home_form = self._get_form(fixture.home_team_id, is_home=True)
            away_form = self._get_form(fixture.away_team_id, is_home=False)
            if not home_form or not away_form:
                logger.debug("No form cache for fixture %d — skipping spread prediction", fixture.id)
                continue

            league = self.session.query(League).filter_by(id=fixture.league_id).first()
            league_espn_id = league.espn_id if league else "unknown"
            params = get_league_params(self.session, league_espn_id)

            if self._ml is not None:
                lambda_home, lambda_away = self._ml.predict(fixture)
            else:
                lambda_home = max(
                    0.1,
                    home_form.goals_scored_avg
                    * (away_form.goals_conceded_avg / LEAGUE_AVG_GOALS)
                    * params.home_advantage,
                )
                lambda_away = max(
                    0.1,
                    away_form.goals_scored_avg * (home_form.goals_conceded_avg / LEAGUE_AVG_GOALS),
                )

            score_matrix = build_score_matrix(lambda_home, lambda_away, rho=params.rho)
            w1, w2 = get_weights(self.session, league_espn_id, "spread")

            offered = self._offered_lines(fixture.id) or [
                ("home" if L < 0 else "away", L) for L in GOAL_LINES
            ]
            for team_side, line in offered:
                win_p, push_p = spread_cover_dc(score_matrix, team_side, line)
                snap = self._latest_snapshot(fixture.id, team_side, line)
                implied, odds = self._implied_and_odds(snap, team_side)
                final_p = blend(win_p, implied, w1, w2)
                edge = (final_p - implied) if implied is not None else None
                tier = edge_tier(edge)
                move = steam_move_pct(self.session, fixture.id, "spread", team_side, line)
                tier, steam_down = apply_steam(tier, move)
                kelly = kelly_fraction(tier, final_p, odds)
                self._upsert(
                    model_id, fixture.id, team_side, line,
                    win_p, push_p, edge, tier, final_p, kelly, steam_down,
                )

        self.session.commit()

    def _get_upcoming_fixtures(self) -> list[Fixture]:
        if self._lead_hours is not None:
            lead = self._lead_hours
        else:
            from app.config import settings
            lead = settings.prediction_lead_hours
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=lead)
        return (
            self.session.query(Fixture)
            .filter(Fixture.status == "scheduled")
            .filter(Fixture.kickoff_at >= now)
            .filter(Fixture.kickoff_at <= cutoff)
            .all()
        )

    def _offered_lines(self, fixture_id: int) -> list[tuple[str, float]]:
        home_rows = (
            self.session.query(OddsSnapshot.spread_home_line)
            .filter(OddsSnapshot.fixture_id == fixture_id)
            .filter(OddsSnapshot.spread_home_line.isnot(None))
            .filter(OddsSnapshot.spread_home_odds.isnot(None))
            .distinct()
            .all()
        )
        away_rows = (
            self.session.query(OddsSnapshot.spread_away_line)
            .filter(OddsSnapshot.fixture_id == fixture_id)
            .filter(OddsSnapshot.spread_away_line.isnot(None))
            .filter(OddsSnapshot.spread_away_odds.isnot(None))
            .distinct()
            .all()
        )
        pairs = {("home", float(r[0])) for r in home_rows}
        pairs.update(("away", float(r[0])) for r in away_rows)
        return sorted(pairs, key=lambda p: (p[0], p[1]))

    def _get_form(self, team_id: int, is_home: bool) -> FormCache | None:
        return self.session.query(FormCache).filter_by(team_id=team_id, is_home=is_home).first()

    def _latest_snapshot(self, fixture_id: int, team_side: str, line: float) -> OddsSnapshot | None:
        q = self.session.query(OddsSnapshot).filter_by(fixture_id=fixture_id)
        if team_side == "home":
            q = q.filter(
                OddsSnapshot.spread_home_line == line,
                OddsSnapshot.spread_home_odds.isnot(None),
            )
        else:
            q = q.filter(
                OddsSnapshot.spread_away_line == line,
                OddsSnapshot.spread_away_odds.isnot(None),
            )
        return q.order_by(OddsSnapshot.captured_at.desc()).first()

    def _implied_and_odds(self, snap: OddsSnapshot | None, team_side: str):
        if snap is None:
            return None, None
        odds = snap.spread_home_odds if team_side == "home" else snap.spread_away_odds
        return _implied_prob(odds), odds

    def _upsert(self, model_id, fixture_id, team_side, line,
                cover_p, push_p, edge, tier, final_p, kelly, steam_down):
        self.session.add(SpreadPrediction(
            model_id=model_id,
            fixture_id=fixture_id,
            team_side=team_side,
            goal_line=line,
            cover_probability=cover_p,
            push_probability=push_p,
            ev_score=edge,
            confidence_tier=tier,
            final_probability=final_p,
            edge_pct=edge,
            kelly_fraction=kelly,
            steam_downgraded=steam_down,
            created_at=datetime.now(timezone.utc),
        ))
