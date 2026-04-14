import logging
from datetime import datetime, timezone, timedelta
from app.db.models import Fixture, FormCache, OddsSnapshot, OUAnalysis, League
from app.dixon_coles import build_score_matrix, ou_probability_dc
from app.league_calibration import get_league_params
from app.market_blend import blend, get_weights
from app.edge_tiers import edge_tier, kelly_fraction
from app.steam_resistance import steam_move_pct, apply_steam

logger = logging.getLogger(__name__)

OU_LINES = [1.5, 2.5, 3.5]  # fallback when fixture has no offered totals
LEAGUE_AVG_GOALS = 1.5


def _implied_prob(decimal_odds: float | None) -> float | None:
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    return 1.0 / decimal_odds


class OUAnalyzer:
    def __init__(self, session, lead_hours: int | None = None, ml_enabled: bool = False):
        self.session = session
        self._lead_hours = lead_hours
        self._ml = None
        if ml_enabled:
            from app.ml_lambda import MLLambdaPredictor
            self._ml = MLLambdaPredictor(session)

    def run(self, model_id: int):
        upcoming = self._get_upcoming_fixtures()
        for fixture in upcoming:
            home_form = self._get_form(fixture.home_team_id, is_home=True)
            away_form = self._get_form(fixture.away_team_id, is_home=False)
            if not home_form or not away_form:
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
            w1, w2 = get_weights(self.session, league_espn_id, "ou")

            offered_lines = self._offered_lines(fixture.id) or OU_LINES
            for line in offered_lines:
                over_p = ou_probability_dc(score_matrix, line)
                under_p = 1.0 - over_p
                if over_p >= under_p:
                    direction, prob = "over", over_p
                else:
                    direction, prob = "under", under_p
                snap = self._latest_snapshot(fixture.id, line, direction)
                implied, odds = self._implied_and_odds(snap, direction)

                final_p = blend(prob, implied, w1, w2)
                edge = (final_p - implied) if implied is not None else None
                tier = edge_tier(edge)
                move = steam_move_pct(self.session, fixture.id, "ou", direction, line)
                tier, steam_down = apply_steam(tier, move)
                kelly = kelly_fraction(tier, final_p, odds)
                self._upsert(
                    model_id, fixture.id, line, direction,
                    prob, edge, tier, final_p, kelly, steam_down,
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

    def _offered_lines(self, fixture_id: int) -> list[float]:
        rows = (
            self.session.query(OddsSnapshot.total_goals_line)
            .filter(OddsSnapshot.fixture_id == fixture_id)
            .filter(OddsSnapshot.total_goals_line.isnot(None))
            .filter(OddsSnapshot.over_odds.isnot(None))
            .filter(OddsSnapshot.under_odds.isnot(None))
            .distinct()
            .all()
        )
        return sorted({float(r[0]) for r in rows})

    def _get_form(self, team_id: int, is_home: bool) -> FormCache | None:
        return self.session.query(FormCache).filter_by(team_id=team_id, is_home=is_home).first()

    def _latest_snapshot(self, fixture_id: int, line: float, direction: str) -> OddsSnapshot | None:
        odds_col = OddsSnapshot.over_odds if direction == "over" else OddsSnapshot.under_odds
        return (
            self.session.query(OddsSnapshot)
            .filter_by(fixture_id=fixture_id)
            .filter(OddsSnapshot.total_goals_line == line)
            .filter(odds_col.isnot(None))
            .order_by(OddsSnapshot.captured_at.desc())
            .first()
        )

    def _implied_and_odds(self, snap: OddsSnapshot | None, direction: str):
        if snap is None:
            return None, None
        odds = snap.over_odds if direction == "over" else snap.under_odds
        return _implied_prob(odds), odds

    def _upsert(self, model_id, fixture_id, line, direction,
                prob, edge, tier, final_p, kelly, steam_down):
        existing = (
            self.session.query(OUAnalysis)
            .filter_by(model_id=model_id, fixture_id=fixture_id, line=line)
            .first()
        )
        if existing:
            existing.direction = direction
            existing.probability = prob
            existing.ev_score = edge
            existing.confidence_tier = tier
            existing.final_probability = final_p
            existing.edge_pct = edge
            existing.kelly_fraction = kelly
            existing.steam_downgraded = steam_down
        else:
            self.session.add(OUAnalysis(
                model_id=model_id,
                fixture_id=fixture_id,
                line=line,
                direction=direction,
                probability=prob,
                ev_score=edge,
                confidence_tier=tier,
                final_probability=final_p,
                edge_pct=edge,
                kelly_fraction=kelly,
                steam_downgraded=steam_down,
                created_at=datetime.now(timezone.utc),
            ))
