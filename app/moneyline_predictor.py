import logging
from datetime import datetime, timezone, timedelta
from app.db.models import Fixture, FormCache, OddsSnapshot, MoneylinePrediction, League, Result
from app.calibration import calibrate_probability, renormalize_probabilities
from app.dixon_coles import build_score_matrix, moneyline_probability_dc
from app.league_calibration import get_league_params
from app.market_blend import blend, get_weights
from app.edge_tiers import edge_tier, kelly_fraction
from app.steam_resistance import steam_move_pct, apply_steam
from sqlalchemy import func

logger = logging.getLogger(__name__)

LEAGUE_AVG_GOALS = 1.5
OUTCOMES = ("home", "draw", "away")
GENERIC_OUTCOME_PRIOR = {"home": 0.46, "draw": 0.27, "away": 0.27}


def _implied_prob(decimal_odds: float | None) -> float | None:
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    return 1.0 / decimal_odds


def _attack_avg(form: FormCache) -> float:
    return form.xg_scored_avg if form.xg_scored_avg is not None else form.goals_scored_avg


def _defense_avg(form: FormCache) -> float:
    return form.xg_conceded_avg if form.xg_conceded_avg is not None else form.goals_conceded_avg


class MoneylinePredictor:
    def __init__(
        self,
        session,
        lead_hours: int | None = None,
        ml_enabled: bool = False,
        market_weights_override: tuple[float, float] | None = None,
        no_market_prior_base: float = 0.20,
        no_market_prior_extra: float = 0.15,
    ):
        self.session = session
        self._lead_hours = lead_hours
        self._ml = None
        self._market_weights_override = market_weights_override
        self._no_market_prior_base = no_market_prior_base
        self._no_market_prior_extra = no_market_prior_extra
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
                    _attack_avg(home_form)
                    * (_defense_avg(away_form) / LEAGUE_AVG_GOALS)
                    * params.home_advantage,
                )
                lambda_away = max(
                    0.1,
                    _attack_avg(away_form) * (_defense_avg(home_form) / LEAGUE_AVG_GOALS),
                )

            score_matrix = build_score_matrix(lambda_home, lambda_away, rho=params.rho)
            home_p, draw_p, away_p = moneyline_probability_dc(score_matrix)
            probs = {"home": home_p, "draw": draw_p, "away": away_p}

            snap = self._latest_snapshot(fixture.id)
            implied_probs = self._outcome_implied_probs(snap)
            if self._has_full_market(implied_probs):
                if self._market_weights_override is not None:
                    w1, w2 = self._market_weights_override
                else:
                    w1, w2 = get_weights(self.session, league_espn_id, "h2h")
                blended_probs = {
                    outcome: blend(
                        probs[outcome],
                        implied_probs.get(outcome),
                        w1,
                        w2,
                    )
                    for outcome in OUTCOMES
                }
            else:
                blended_probs = self._shrink_without_market(fixture.league_id, probs)

            calibrated_probs = {
                outcome: calibrate_probability(self.session, model_id, "h2h", probability)
                for outcome, probability in blended_probs.items()
            }
            final_probs = renormalize_probabilities(calibrated_probs)

            for outcome in OUTCOMES:
                prob = probs[outcome]
                odds = self._outcome_odds(snap, outcome)
                implied = implied_probs.get(outcome)
                final_p = final_probs[outcome]
                edge = (final_p - implied) if implied is not None else None
                tier = edge_tier(edge)
                move = steam_move_pct(self.session, fixture.id, "h2h", outcome, 0.0)
                tier, steam_down = apply_steam(tier, move)
                kelly = kelly_fraction(tier, final_p, odds)
                self._upsert(
                    model_id, fixture.id, outcome,
                    prob, edge, tier, final_p, kelly, steam_down, snap.id if snap else None,
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

    def _outcome_implied_probs(self, snap: OddsSnapshot | None) -> dict[str, float | None]:
        if snap is None:
            return {outcome: None for outcome in OUTCOMES}
        raw = {
            "home": _implied_prob(snap.home_odds),
            "draw": _implied_prob(snap.draw_odds),
            "away": _implied_prob(snap.away_odds),
        }
        if any(value is None for value in raw.values()):
            return raw
        total = sum(value for value in raw.values() if value is not None)
        if total <= 0:
            return raw
        return {outcome: value / total for outcome, value in raw.items() if value is not None}

    def _has_full_market(self, implied_probs: dict[str, float | None]) -> bool:
        return all(implied_probs.get(outcome) is not None for outcome in OUTCOMES)

    def _shrink_without_market(
        self,
        league_id: int,
        model_probs: dict[str, float],
    ) -> dict[str, float]:
        prior, prior_weight = self._league_outcome_prior(league_id)
        model_weight = 1.0 - prior_weight
        return renormalize_probabilities({
            outcome: (model_weight * model_probs[outcome]) + (prior_weight * prior[outcome])
            for outcome in OUTCOMES
        })

    def _league_outcome_prior(self, league_id: int) -> tuple[dict[str, float], float]:
        rows = (
            self.session.query(Result.outcome, func.count(Result.id))
            .join(Fixture, Fixture.id == Result.fixture_id)
            .filter(Fixture.league_id == league_id)
            .filter(Result.outcome.in_(OUTCOMES))
            .group_by(Result.outcome)
            .all()
        )
        counts = {outcome: 0 for outcome in OUTCOMES}
        for outcome, count in rows:
            counts[outcome] = int(count)
        total = sum(counts.values())
        if total <= 0:
            return GENERIC_OUTCOME_PRIOR.copy(), 0.20

        empirical = {outcome: counts[outcome] / total for outcome in OUTCOMES}
        empirical_strength = min(1.0, total / 100.0)
        prior = renormalize_probabilities({
            outcome: (
                (empirical_strength * empirical[outcome])
                + ((1.0 - empirical_strength) * GENERIC_OUTCOME_PRIOR[outcome])
            )
            for outcome in OUTCOMES
        })
        prior_weight = self._no_market_prior_base + (
            self._no_market_prior_extra * min(1.0, total / 400.0)
        )
        return prior, prior_weight

    def _upsert(self, model_id, fixture_id, outcome,
                prob, edge, tier, final_p, kelly, steam_down, odds_snapshot_id):
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
            existing.odds_snapshot_id = odds_snapshot_id
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
                odds_snapshot_id=odds_snapshot_id,
                created_at=datetime.now(timezone.utc),
            ))
