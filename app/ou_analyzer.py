import logging
from datetime import datetime, timezone, timedelta
from app.db.models import Fixture, FormCache, OddsSnapshot, OUAnalysis, League, Result
from app.calibration import calibrate_probability
from app.dixon_coles import build_score_matrix, ou_probability_dc
from app.league_calibration import get_league_params
from app.market_blend import blend, get_weights
from app.edge_tiers import edge_tier, kelly_fraction
from app.steam_resistance import steam_move_pct, apply_steam

logger = logging.getLogger(__name__)

OU_LINES = [1.5, 2.5, 3.5]  # fallback when fixture has no offered totals
LEAGUE_AVG_GOALS = 1.5
GENERIC_OVER_PRIOR = {
    1.5: 0.74,
    2.5: 0.52,
    3.5: 0.30,
}


def _implied_prob(decimal_odds: float | None) -> float | None:
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    return 1.0 / decimal_odds


def _attack_avg(form: FormCache) -> float:
    return form.xg_scored_avg if form.xg_scored_avg is not None else form.goals_scored_avg


def _defense_avg(form: FormCache) -> float:
    return form.xg_conceded_avg if form.xg_conceded_avg is not None else form.goals_conceded_avg


class OUAnalyzer:
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
                    _attack_avg(home_form)
                    * (_defense_avg(away_form) / LEAGUE_AVG_GOALS)
                    * params.home_advantage,
                )
                lambda_away = max(
                    0.1,
                    _attack_avg(away_form) * (_defense_avg(home_form) / LEAGUE_AVG_GOALS),
                )

            score_matrix = build_score_matrix(lambda_home, lambda_away, rho=params.rho)
            if self._market_weights_override is not None:
                w1, w2 = self._market_weights_override
            else:
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
                if implied is not None:
                    final_p = blend(prob, implied, w1, w2)
                else:
                    final_p = self._shrink_without_market(fixture.league_id, line, direction, prob)
                final_p = calibrate_probability(self.session, model_id, "ou", final_p)
                edge = (final_p - implied) if implied is not None else None
                tier = edge_tier(edge)
                move = steam_move_pct(self.session, fixture.id, "ou", direction, line)
                tier, steam_down = apply_steam(tier, move)
                kelly = kelly_fraction(tier, final_p, odds)
                self._upsert(
                    model_id, fixture.id, line, direction,
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

    def _shrink_without_market(self, league_id: int, line: float, direction: str, prob: float) -> float:
        prior, prior_weight = self._ou_direction_prior(league_id, line, direction)
        return ((1.0 - prior_weight) * prob) + (prior_weight * prior)

    def _ou_direction_prior(self, league_id: int, line: float, direction: str) -> tuple[float, float]:
        rows = (
            self.session.query(Result.total_goals)
            .join(Fixture, Fixture.id == Result.fixture_id)
            .filter(Fixture.league_id == league_id)
            .filter(Result.total_goals.isnot(None))
            .all()
        )
        total = len(rows)
        generic_over = GENERIC_OVER_PRIOR.get(line, 0.5)
        generic_direction = generic_over if direction == "over" else (1.0 - generic_over)
        if total <= 0:
            return generic_direction, 0.20

        hits = 0
        for (total_goals,) in rows:
            if direction == "over" and total_goals > line:
                hits += 1
            elif direction == "under" and total_goals < line:
                hits += 1

        empirical = hits / total
        empirical_strength = min(1.0, total / 120.0)
        prior = (empirical_strength * empirical) + ((1.0 - empirical_strength) * generic_direction)
        prior_weight = self._no_market_prior_base + (
            self._no_market_prior_extra * min(1.0, total / 400.0)
        )
        return prior, prior_weight

    def _upsert(self, model_id, fixture_id, line, direction,
                prob, edge, tier, final_p, kelly, steam_down, odds_snapshot_id):
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
            existing.odds_snapshot_id = odds_snapshot_id
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
                odds_snapshot_id=odds_snapshot_id,
                created_at=datetime.now(timezone.utc),
            ))
