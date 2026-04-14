import logging
from datetime import datetime, timezone, timedelta
from app.db.models import Fixture, FormCache, OddsSnapshot, MoneylinePrediction, League
from app.dixon_coles import build_score_matrix, moneyline_probability_dc
from app.league_calibration import get_league_params
from app.market_blend import blend, get_weights
from app.edge_tiers import edge_tier, kelly_fraction
from app.steam_resistance import steam_move_pct, apply_steam

logger = logging.getLogger(__name__)

LEAGUE_AVG_GOALS = 1.5
OUTCOMES = ("home", "draw", "away")


def _implied_prob(decimal_odds: float | None) -> float | None:
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    return 1.0 / decimal_odds


class MoneylinePredictor:
    def __init__(self, session, lead_hours: int | None = None, ml_enabled: bool = False):
        self.session = session
        self._lead_hours = lead_hours
        self._ml = None
        if ml_enabled:
            from app.ml_lambda import MLLambdaPredictor
            self._ml = MLLambdaPredictor(session)

    def run(self, model_id: int):
        for fixture in self._get_upcoming_fixtures():
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
            home_p, draw_p, away_p = moneyline_probability_dc(score_matrix)
            probs = {"home": home_p, "draw": draw_p, "away": away_p}

            w1, w2 = get_weights(self.session, league_espn_id, "h2h")
            snap = self._latest_snapshot(fixture.id)

            for outcome in OUTCOMES:
                prob = probs[outcome]
                odds = self._outcome_odds(snap, outcome)
                implied = _implied_prob(odds)
                final_p = blend(prob, implied, w1, w2)
                edge = (final_p - implied) if implied is not None else None
                tier = edge_tier(edge)
                move = steam_move_pct(self.session, fixture.id, "h2h", outcome, 0.0)
                tier, steam_down = apply_steam(tier, move)
                kelly = kelly_fraction(tier, final_p, odds)
                self._upsert(
                    model_id, fixture.id, outcome,
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

    def _get_form(self, team_id: int, is_home: bool) -> FormCache | None:
        return self.session.query(FormCache).filter_by(team_id=team_id, is_home=is_home).first()

    def _latest_snapshot(self, fixture_id: int) -> OddsSnapshot | None:
        return (
            self.session.query(OddsSnapshot)
            .filter_by(fixture_id=fixture_id)
            .filter(OddsSnapshot.home_odds.isnot(None))
            .filter(OddsSnapshot.away_odds.isnot(None))
            .order_by(OddsSnapshot.captured_at.desc())
            .first()
        )

    def _outcome_odds(self, snap: OddsSnapshot | None, outcome: str) -> float | None:
        if snap is None:
            return None
        return {"home": snap.home_odds, "draw": snap.draw_odds, "away": snap.away_odds}[outcome]

    def _upsert(self, model_id, fixture_id, outcome,
                prob, edge, tier, final_p, kelly, steam_down):
        existing = (
            self.session.query(MoneylinePrediction)
            .filter_by(model_id=model_id, fixture_id=fixture_id, outcome=outcome)
            .first()
        )
        if existing:
            existing.probability = prob
            existing.ev_score = edge
            existing.confidence_tier = tier
            existing.final_probability = final_p
            existing.edge_pct = edge
            existing.kelly_fraction = kelly
            existing.steam_downgraded = steam_down
        else:
            self.session.add(MoneylinePrediction(
                model_id=model_id,
                fixture_id=fixture_id,
                outcome=outcome,
                probability=prob,
                ev_score=edge,
                confidence_tier=tier,
                final_probability=final_p,
                edge_pct=edge,
                kelly_fraction=kelly,
                steam_downgraded=steam_down,
                created_at=datetime.now(timezone.utc),
            ))
