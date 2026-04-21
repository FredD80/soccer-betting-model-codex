from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.db.models import (
    BacktestRun,
    FavoriteSgpBacktestRow,
    Fixture,
    HistoricalOddsBundle,
    MoneylinePrediction,
    OddsSnapshot,
    Result,
    SpreadPrediction,
    OUAnalysis,
    ModelVersion,
)
from app.bully_engine import EloFormPredictor

_ALLOWED_TIERS = ("HIGH", "ELITE")
_SYNTH_SGP_FACTOR = 0.75


@dataclass
class BacktestSummary:
    market: str
    model_id: int
    total: int
    correct: int
    accuracy: float
    roi: float
    win_two_plus_hit_rate: float | None = None
    two_plus_hit_rate: float | None = None
    clean_sheet_hit_rate: float | None = None
    two_plus_given_win_rate: float | None = None
    clean_sheet_given_win_rate: float | None = None


class PickBacktester:
    def __init__(self, session):
        self.session = session

    def run(
        self,
        date_from: datetime,
        date_to: datetime,
        markets: tuple[str, ...] = ("spread", "ou", "moneyline", "bully"),
        allowed_tiers: tuple[str, ...] = _ALLOWED_TIERS,
        backtest_job_id: int | None = None,
    ) -> list[BacktestSummary]:
        summaries: list[BacktestSummary] = []
        market_handlers = {
            "spread": self._backtest_spread,
            "ou": self._backtest_ou,
            "moneyline": self._backtest_moneyline,
            "bully": self._backtest_bully,
        }
        for market in markets:
            handler = market_handlers[market]
            summaries.extend(handler(date_from, date_to, allowed_tiers))

        for summary in summaries:
            self.session.add(
                BacktestRun(
                    model_id=summary.model_id,
                    backtest_job_id=backtest_job_id,
                    bet_type=summary.market,
                    date_from=date_from,
                    date_to=date_to,
                    total=summary.total,
                    correct=summary.correct,
                    accuracy=summary.accuracy,
                    roi=summary.roi,
                    two_plus_hit_rate=summary.two_plus_hit_rate,
                    clean_sheet_hit_rate=summary.clean_sheet_hit_rate,
                    two_plus_given_win_rate=summary.two_plus_given_win_rate,
                    clean_sheet_given_win_rate=summary.clean_sheet_given_win_rate,
                    run_at=datetime.now(timezone.utc),
                )
            )
        self.session.commit()
        return summaries

    def _completed_fixtures(self, date_from: datetime, date_to: datetime):
        return (
            self.session.query(Fixture)
            .filter(Fixture.status == "completed")
            .filter(Fixture.kickoff_at >= date_from)
            .filter(Fixture.kickoff_at <= date_to)
            .all()
        )

    def _backtest_spread(self, date_from: datetime, date_to: datetime, allowed_tiers: tuple[str, ...]):
        stats: dict[int, dict[str, float]] = {}
        for fixture in self._completed_fixtures(date_from, date_to):
            result = self.session.query(Result).filter_by(fixture_id=fixture.id).first()
            if not result or result.home_score is None or result.away_score is None:
                continue

            picks = (
                self.session.query(SpreadPrediction)
                .filter(SpreadPrediction.fixture_id == fixture.id)
                .filter(SpreadPrediction.confidence_tier.in_(allowed_tiers))
                .order_by(SpreadPrediction.ev_score.desc())
                .all()
            )
            best_by_model: dict[int, SpreadPrediction] = {}
            for pick in picks:
                if not self._is_us_style_line(pick.goal_line):
                    continue
                best_by_model.setdefault(pick.model_id, pick)

            goal_diff = result.home_score - result.away_score
            for model_id, pick in best_by_model.items():
                odds = self._spread_odds(pick)
                multiplier = self._spread_multiplier(goal_diff, pick.team_side, pick.goal_line)
                self._accumulate(stats, model_id, multiplier, odds)

        return self._summaries("spread", stats)

    def _backtest_ou(self, date_from: datetime, date_to: datetime, allowed_tiers: tuple[str, ...]):
        stats: dict[int, dict[str, float]] = {}
        for fixture in self._completed_fixtures(date_from, date_to):
            result = self.session.query(Result).filter_by(fixture_id=fixture.id).first()
            if not result or result.total_goals is None:
                continue

            picks = (
                self.session.query(OUAnalysis)
                .filter(OUAnalysis.fixture_id == fixture.id)
                .filter(OUAnalysis.confidence_tier.in_(allowed_tiers))
                .order_by(OUAnalysis.ev_score.desc())
                .all()
            )
            best_by_model: dict[int, OUAnalysis] = {}
            for pick in picks:
                best_by_model.setdefault(pick.model_id, pick)

            for model_id, pick in best_by_model.items():
                odds = self._ou_odds(pick)
                multiplier = self._ou_multiplier(result.total_goals, pick.direction, pick.line)
                self._accumulate(stats, model_id, multiplier, odds)

        return self._summaries("ou", stats)

    def _backtest_moneyline(self, date_from: datetime, date_to: datetime, allowed_tiers: tuple[str, ...]):
        stats: dict[int, dict[str, float]] = {}
        for fixture in self._completed_fixtures(date_from, date_to):
            result = self.session.query(Result).filter_by(fixture_id=fixture.id).first()
            if not result or result.outcome is None:
                continue

            picks = (
                self.session.query(MoneylinePrediction)
                .filter(MoneylinePrediction.fixture_id == fixture.id)
                .filter(MoneylinePrediction.confidence_tier.in_(allowed_tiers))
                .order_by(MoneylinePrediction.ev_score.desc())
                .all()
            )
            best_by_model: dict[int, MoneylinePrediction] = {}
            for pick in picks:
                best_by_model.setdefault(pick.model_id, pick)

            for model_id, pick in best_by_model.items():
                odds = self._moneyline_odds(pick)
                multiplier = 1.0 if pick.outcome == result.outcome else -1.0
                self._accumulate(stats, model_id, multiplier, odds)

        return self._summaries("moneyline", stats)

    def _backtest_bully(self, date_from: datetime, date_to: datetime, allowed_tiers: tuple[str, ...]):
        stats: dict[int, dict[str, float]] = {}
        model = (
            self.session.query(ModelVersion)
            .filter(ModelVersion.name == "elo_bully_v1")
            .filter(ModelVersion.active.is_(True))
            .order_by(ModelVersion.created_at.desc())
            .first()
        )
        if model is None:
            return []

        predictor = EloFormPredictor(self.session, enable_understat_fetch=False)
        for fixture in self._completed_fixtures(date_from, date_to):
            result = self.session.query(Result).filter_by(fixture_id=fixture.id).first()
            if (
                not result
                or result.outcome is None
                or result.home_score is None
                or result.away_score is None
            ):
                continue

            prediction = predictor.predict_fixture(fixture, as_of=fixture.kickoff_at)
            if prediction is None or not prediction.is_bully_spot:
                continue

            odds = self._bully_joint_odds(fixture.id, prediction.favorite_side, fixture.kickoff_at)
            favorite_goals = result.home_score if prediction.favorite_side == "home" else result.away_score
            underdog_goals = result.away_score if prediction.favorite_side == "home" else result.home_score
            favorite_win = prediction.favorite_side == result.outcome
            sgp_hit = favorite_win and favorite_goals >= 2
            self._accumulate(
                stats,
                model.id,
                1.0 if sgp_hit else -1.0,
                odds,
                two_plus_hit=1.0 if favorite_goals >= 2 else 0.0,
                clean_sheet_hit=1.0 if underdog_goals == 0 else 0.0,
                two_plus_given_win=1.0 if favorite_win and favorite_goals >= 2 else 0.0,
                clean_sheet_given_win=1.0 if favorite_win and underdog_goals == 0 else 0.0,
            )

        return self._summaries("bully", stats)

    def _spread_odds(self, pick: SpreadPrediction) -> float | None:
        query = self.session.query(OddsSnapshot).filter(OddsSnapshot.fixture_id == pick.fixture_id)
        query = query.filter(OddsSnapshot.captured_at <= pick.created_at)
        if pick.team_side == "home":
            query = query.filter(
                OddsSnapshot.spread_home_line == pick.goal_line,
                OddsSnapshot.spread_home_odds.isnot(None),
            )
            snap = query.order_by(OddsSnapshot.captured_at.desc()).first()
            return snap.spread_home_odds if snap else None

        query = query.filter(
            OddsSnapshot.spread_away_line == pick.goal_line,
            OddsSnapshot.spread_away_odds.isnot(None),
        )
        snap = query.order_by(OddsSnapshot.captured_at.desc()).first()
        return snap.spread_away_odds if snap else None

    def _ou_odds(self, pick: OUAnalysis) -> float | None:
        query = (
            self.session.query(OddsSnapshot)
            .filter(OddsSnapshot.fixture_id == pick.fixture_id)
            .filter(OddsSnapshot.total_goals_line == pick.line)
            .filter(OddsSnapshot.captured_at <= pick.created_at)
        )
        if pick.direction == "over":
            query = query.filter(OddsSnapshot.over_odds.isnot(None))
            snap = query.order_by(OddsSnapshot.captured_at.desc()).first()
            return snap.over_odds if snap else None
        query = query.filter(OddsSnapshot.under_odds.isnot(None))
        snap = query.order_by(OddsSnapshot.captured_at.desc()).first()
        return snap.under_odds if snap else None

    def _moneyline_odds(self, pick: MoneylinePrediction) -> float | None:
        snap = (
            self.session.query(OddsSnapshot)
            .filter(OddsSnapshot.fixture_id == pick.fixture_id)
            .filter(OddsSnapshot.captured_at <= pick.created_at)
            .filter(OddsSnapshot.home_odds.isnot(None))
            .filter(OddsSnapshot.away_odds.isnot(None))
            .order_by(OddsSnapshot.captured_at.desc())
            .first()
        )
        if not snap:
            return None
        return {"home": snap.home_odds, "draw": snap.draw_odds, "away": snap.away_odds}[pick.outcome]

    def _bully_joint_odds(self, fixture_id: int, favorite_side: str, created_at: datetime | None) -> float | None:
        prebuilt_odds = self._favorite_sgp_backtest_odds(fixture_id, favorite_side)
        if prebuilt_odds is not None:
            return prebuilt_odds

        historical_direct = self._historical_bully_joint_odds(fixture_id, favorite_side)
        if historical_direct is not None:
            return historical_direct

        historical_components = self._historical_bully_components(fixture_id, favorite_side)
        if historical_components is not None:
            synthetic_odds = self._synthesized_bully_joint_odds(
                favorite_odds=historical_components[0],
                opposite_odds=historical_components[1],
                team_total_over_odds=historical_components[2],
                team_total_under_odds=historical_components[3],
            )
            if synthetic_odds is not None:
                return synthetic_odds

        query = self.session.query(OddsSnapshot).filter(OddsSnapshot.fixture_id == fixture_id)
        if created_at is not None:
            query = query.filter(OddsSnapshot.captured_at <= created_at)
        if favorite_side == "home":
            query = query.filter(OddsSnapshot.home_odds.isnot(None))
        else:
            query = query.filter(OddsSnapshot.away_odds.isnot(None))
        snap = query.order_by(OddsSnapshot.captured_at.desc()).first()
        if not snap:
            return None
        team_total_over, team_total_under = self._favorite_team_total_1_5_odds(snap, favorite_side)
        favorite_odds = snap.home_odds if favorite_side == "home" else snap.away_odds
        opposite_odds = snap.away_odds if favorite_side == "home" else snap.home_odds
        synthetic_odds = self._synthesized_bully_joint_odds(
            favorite_odds=favorite_odds,
            opposite_odds=opposite_odds,
            team_total_over_odds=team_total_over,
            team_total_under_odds=team_total_under,
        )
        if synthetic_odds is not None:
            return synthetic_odds
        return favorite_odds

    def _favorite_sgp_backtest_odds(self, fixture_id: int, favorite_side: str) -> float | None:
        rows = (
            self.session.query(FavoriteSgpBacktestRow)
            .filter(FavoriteSgpBacktestRow.fixture_id == fixture_id)
            .filter(FavoriteSgpBacktestRow.favorite_side == favorite_side)
            .filter(FavoriteSgpBacktestRow.sgp_usable_odds.isnot(None))
            .all()
        )
        if not rows:
            return None

        odds_type_rank = {"closing": 0, "peak": 1, "opening": 2}
        bookmaker_rank = {1: 0, 2: 1, 3: 2, 4: 3}
        preferred = sorted(
            rows,
            key=lambda row: (
                odds_type_rank.get(row.odds_type, 99),
                bookmaker_rank.get(row.bookmaker_id, 99),
            ),
        )[0]
        return preferred.sgp_usable_odds

    def _historical_bully_joint_odds(self, fixture_id: int, favorite_side: str) -> float | None:
        bundle = self._preferred_historical_bundle(
            fixture_id,
            lambda row: (
                row.home_win_and_home_over_1_5_odds is not None
                if favorite_side == "home"
                else row.away_win_and_away_over_1_5_odds is not None
            ),
        )
        if bundle is None:
            return None
        return (
            bundle.home_win_and_home_over_1_5_odds
            if favorite_side == "home"
            else bundle.away_win_and_away_over_1_5_odds
        )

    def _historical_bully_components(self, fixture_id: int, favorite_side: str) -> tuple[float, float, float, float] | None:
        bundle = self._preferred_historical_bundle(
            fixture_id,
            lambda row: (
                self._historical_component_tuple(row, favorite_side) is not None
            ),
        )
        if bundle is None:
            return None
        return self._historical_component_tuple(bundle, favorite_side)

    def _historical_component_tuple(
        self,
        bundle: HistoricalOddsBundle,
        favorite_side: str,
    ) -> tuple[float, float, float, float] | None:
        favorite_odds = bundle.home_odds if favorite_side == "home" else bundle.away_odds
        opposite_odds = bundle.away_odds if favorite_side == "home" else bundle.home_odds
        team_total_over = (
            bundle.home_team_total_1_5_over_odds
            if favorite_side == "home"
            else bundle.away_team_total_1_5_over_odds
        )
        team_total_under = (
            bundle.home_team_total_1_5_under_odds
            if favorite_side == "home"
            else bundle.away_team_total_1_5_under_odds
        )
        if not favorite_odds or not opposite_odds or not team_total_over or not team_total_under:
            return None
        return favorite_odds, opposite_odds, team_total_over, team_total_under

    def _preferred_historical_bundle(
        self,
        fixture_id: int,
        predicate,
    ) -> HistoricalOddsBundle | None:
        rows = (
            self.session.query(HistoricalOddsBundle)
            .filter(HistoricalOddsBundle.fixture_id == fixture_id)
            .all()
        )
        if not rows:
            return None

        odds_type_rank = {"closing": 0, "peak": 1, "opening": 2}
        bookmaker_rank = {1: 0, 2: 1, 3: 2, 4: 3}
        ordered = sorted(
            rows,
            key=lambda row: (
                odds_type_rank.get(row.odds_type, 99),
                bookmaker_rank.get(row.bookmaker_id, 99),
            ),
        )
        for row in ordered:
            if predicate(row):
                return row
        return None

    def _favorite_team_total_1_5_odds(self, snap: OddsSnapshot, favorite_side: str) -> tuple[float | None, float | None]:
        if favorite_side == "home":
            return snap.home_team_total_1_5_over_odds, snap.home_team_total_1_5_under_odds
        return snap.away_team_total_1_5_over_odds, snap.away_team_total_1_5_under_odds

    def _synthesized_bully_joint_odds(
        self,
        *,
        favorite_odds: float | None,
        opposite_odds: float | None,
        team_total_over_odds: float | None,
        team_total_under_odds: float | None,
    ) -> float | None:
        if not favorite_odds or not opposite_odds or not team_total_over_odds or not team_total_under_odds:
            return None
        p_win_fair = self._devig_two_way_first(favorite_odds, opposite_odds)
        p_over_fair = self._devig_two_way_first(team_total_over_odds, team_total_under_odds)
        if p_win_fair is None or p_over_fair is None:
            return None
        market_prob = min(0.99, max(0.0, (p_win_fair * p_over_fair) / _SYNTH_SGP_FACTOR))
        if market_prob <= 0.0:
            return None
        return 1.0 / market_prob

    def _devig_two_way_first(self, odds_a: float, odds_b: float) -> float | None:
        if odds_a <= 1.0 or odds_b <= 1.0:
            return None
        imp_a = 1.0 / odds_a
        imp_b = 1.0 / odds_b
        overround = imp_a + imp_b
        if overround <= 0.0:
            return None
        return imp_a / overround

    def _accumulate(
        self,
        stats: dict[int, dict[str, float]],
        model_id: int,
        multiplier: float,
        odds: float | None,
        *,
        two_plus_hit: float | None = None,
        clean_sheet_hit: float | None = None,
        two_plus_given_win: float | None = None,
        clean_sheet_given_win: float | None = None,
    ):
        row = stats.setdefault(
            model_id,
            {
                "total": 0.0,
                "correct": 0.0,
                "roi_sum": 0.0,
                "two_plus_hits": 0.0,
                "clean_sheet_hits": 0.0,
                "two_plus_given_win_hits": 0.0,
                "clean_sheet_given_win_hits": 0.0,
            },
        )
        row["total"] += 1
        if multiplier > 0:
            row["correct"] += 1
            row["roi_sum"] += (odds - 1.0) if odds is not None else 0.0
        elif multiplier == 0:
            row["roi_sum"] += 0.0
        else:
            row["roi_sum"] += -1.0
        if two_plus_hit is not None:
            row["two_plus_hits"] += two_plus_hit
        if clean_sheet_hit is not None:
            row["clean_sheet_hits"] += clean_sheet_hit
        if two_plus_given_win is not None:
            row["two_plus_given_win_hits"] += two_plus_given_win
        if clean_sheet_given_win is not None:
            row["clean_sheet_given_win_hits"] += clean_sheet_given_win

    def _summaries(self, market: str, stats: dict[int, dict[str, float]]) -> list[BacktestSummary]:
        summaries = []
        for model_id, row in stats.items():
            total = int(row["total"])
            correct = int(row["correct"])
            summaries.append(
                BacktestSummary(
                    market=market,
                    model_id=model_id,
                    total=total,
                    correct=correct,
                    accuracy=(correct / total) if total else 0.0,
                    roi=(row["roi_sum"] / total) if total else 0.0,
                    win_two_plus_hit_rate=(
                        row["two_plus_given_win_hits"] / total
                    ) if market == "bully" and total else None,
                    two_plus_hit_rate=(row["two_plus_hits"] / total) if market == "bully" and total else None,
                    clean_sheet_hit_rate=(row["clean_sheet_hits"] / total) if market == "bully" and total else None,
                    two_plus_given_win_rate=(
                        row["two_plus_given_win_hits"] / correct
                    ) if market == "bully" and correct else None,
                    clean_sheet_given_win_rate=(
                        row["clean_sheet_given_win_hits"] / correct
                    ) if market == "bully" and correct else None,
                )
            )
        return summaries

    @staticmethod
    def _is_us_style_line(line: float) -> bool:
        return abs(round(line * 2) - line * 2) < 1e-6

    @staticmethod
    def _spread_multiplier(goal_diff: int, team_side: str, line: float) -> float:
        adjusted = goal_diff + line if team_side == "home" else -goal_diff + line
        if adjusted > 0:
            return 1.0
        if adjusted == 0:
            return 0.0
        return -1.0

    @staticmethod
    def _ou_multiplier(total_goals: int, direction: str, line: float) -> float:
        if total_goals == line:
            return 0.0
        if direction == "over":
            return 1.0 if total_goals > line else -1.0
        return 1.0 if total_goals < line else -1.0
