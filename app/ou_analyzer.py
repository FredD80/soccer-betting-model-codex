import logging
from datetime import datetime, timezone, timedelta
from app.db.models import Fixture, FormCache, OddsSnapshot, OUAnalysis, League
from app.dixon_coles import build_score_matrix, ou_probability_dc
from app.league_calibration import get_league_params

logger = logging.getLogger(__name__)

OU_LINES = [1.5, 2.5, 3.5]
LEAGUE_AVG_GOALS = 1.5


def _implied_prob(decimal_odds: float | None) -> float | None:
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    return 1.0 / decimal_odds


def _confidence_tier(ev: float | None) -> str:
    if ev is None:
        return "SKIP"
    if ev >= 0.10:
        return "ELITE"
    if ev >= 0.05:
        return "HIGH"
    if ev >= 0.02:
        return "MEDIUM"
    return "SKIP"


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

            # Per-league Dixon-Coles calibration
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
            snap = self._latest_snapshot(fixture.id)

            for line in OU_LINES:
                over_p = ou_probability_dc(score_matrix, line)
                under_p = 1.0 - over_p
                if over_p >= under_p:
                    direction = "over"
                    prob = over_p
                    ev = self._compute_ev(over_p, snap, "over")
                else:
                    direction = "under"
                    prob = under_p
                    ev = self._compute_ev(under_p, snap, "under")

                tier = _confidence_tier(ev)
                self._upsert(model_id, fixture.id, line, direction, prob, ev, tier)

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
            .order_by(OddsSnapshot.captured_at.desc())
            .first()
        )

    def _compute_ev(self, prob: float, snap: OddsSnapshot | None, direction: str) -> float | None:
        if snap is None:
            return None
        if direction == "over":
            implied = _implied_prob(snap.over_odds)
        else:
            implied = _implied_prob(snap.under_odds)
        if implied is None:
            return None
        return prob - implied

    def _upsert(self, model_id, fixture_id, line, direction, prob, ev, tier):
        existing = (
            self.session.query(OUAnalysis)
            .filter_by(model_id=model_id, fixture_id=fixture_id, line=line)
            .first()
        )
        if existing:
            existing.direction = direction
            existing.probability = prob
            existing.ev_score = ev
            existing.confidence_tier = tier
        else:
            self.session.add(OUAnalysis(
                model_id=model_id,
                fixture_id=fixture_id,
                line=line,
                direction=direction,
                probability=prob,
                ev_score=ev,
                confidence_tier=tier,
                created_at=datetime.now(timezone.utc),
            ))
