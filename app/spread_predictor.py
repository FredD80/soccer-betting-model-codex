import math
import logging
from datetime import datetime, timezone, timedelta
from app.db.models import Fixture, FormCache, OddsSnapshot, SpreadPrediction

logger = logging.getLogger(__name__)

GOAL_LINES = [-1.5, -1.0, -0.5, 0.5, 1.0, 1.5]
MAX_GOALS = 10
LEAGUE_AVG_GOALS = 1.5  # normalisation constant for attack × defense formula


def _poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def cover_probability(lambda_home: float, lambda_away: float, line: float) -> tuple[float, float]:
    """
    Returns (win_probability, push_probability) for a goal-line spread bet.

    line < 0  →  home spread  (e.g., -0.5: home must win; -1.0: home wins by 2+)
    line > 0  →  away spread  (e.g., +0.5: away covers on draw/win; +1.0: away covers unless home wins by 2+)

    Push only occurs on integer lines (-1.0, +1.0) when home wins by exactly 1.
    All lines 0.5-spaced (e.g., -0.5, -1.5, +0.5, +1.5) have push_probability == 0.
    """
    win_p = 0.0
    push_p = 0.0
    is_integer_line = abs(round(abs(line)) - abs(line)) < 0.01

    for h in range(MAX_GOALS + 1):
        ph = _poisson_pmf(h, lambda_home)
        for a in range(MAX_GOALS + 1):
            pa = _poisson_pmf(a, lambda_away)
            margin = h - a  # positive = home leading

            if line < 0:
                threshold = abs(line)
                if margin > threshold:
                    win_p += ph * pa
                elif is_integer_line and margin == round(threshold):
                    push_p += ph * pa
            else:
                threshold = line
                if margin < threshold:
                    win_p += ph * pa
                elif is_integer_line and margin == round(threshold):
                    push_p += ph * pa

    return win_p, push_p


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


class SpreadPredictor:
    def __init__(self, session, lead_hours: int | None = None):
        self.session = session
        self._lead_hours = lead_hours

    def run(self, model_id: int):
        upcoming = self._get_upcoming_fixtures()
        for fixture in upcoming:
            home_form = self._get_form(fixture.home_team_id, is_home=True)
            away_form = self._get_form(fixture.away_team_id, is_home=False)
            if not home_form or not away_form:
                logger.debug("No form cache for fixture %d — skipping spread prediction", fixture.id)
                continue

            # Attack × Defence / league_avg normalisation (standard Dixon-Coles precursor)
            lambda_home = max(0.1, home_form.goals_scored_avg * (away_form.goals_conceded_avg / LEAGUE_AVG_GOALS))
            lambda_away = max(0.1, away_form.goals_scored_avg * (home_form.goals_conceded_avg / LEAGUE_AVG_GOALS))

            snap = self._latest_snapshot(fixture.id)

            for line in GOAL_LINES:
                win_p, push_p = cover_probability(lambda_home, lambda_away, line)
                team_side = "home" if line < 0 else "away"
                ev = self._compute_ev(win_p, snap, line)
                tier = _confidence_tier(ev)
                self._upsert(model_id, fixture.id, team_side, line, win_p, push_p, ev, tier)

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

    def _compute_ev(self, win_p: float, snap: OddsSnapshot | None, line: float) -> float | None:
        if snap is None:
            return None
        if line < 0:
            implied = _implied_prob(snap.spread_home_odds)
        else:
            implied = _implied_prob(snap.spread_away_odds)
        if implied is None:
            return None
        return win_p - implied

    def _upsert(self, model_id, fixture_id, team_side, line, cover_p, push_p, ev, tier):
        existing = (
            self.session.query(SpreadPrediction)
            .filter_by(model_id=model_id, fixture_id=fixture_id, goal_line=line)
            .first()
        )
        if existing:
            existing.cover_probability = cover_p
            existing.push_probability = push_p
            existing.ev_score = ev
            existing.confidence_tier = tier
        else:
            self.session.add(SpreadPrediction(
                model_id=model_id,
                fixture_id=fixture_id,
                team_side=team_side,
                goal_line=line,
                cover_probability=cover_p,
                push_probability=push_p,
                ev_score=ev,
                confidence_tier=tier,
                created_at=datetime.now(timezone.utc),
            ))
