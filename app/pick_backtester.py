from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.db.models import (
    BacktestRun,
    Fixture,
    MoneylinePrediction,
    OddsSnapshot,
    Result,
    SpreadPrediction,
    OUAnalysis,
    ModelVersion,
)
from app.bully_engine import EloFormPredictor

_ALLOWED_TIERS = ("HIGH", "ELITE")


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

            odds = self._bully_odds(fixture.id, prediction.favorite_side, fixture.kickoff_at)
            multiplier = 1.0 if prediction.favorite_side == result.outcome else -1.0
            favorite_goals = result.home_score if prediction.favorite_side == "home" else result.away_score
            underdog_goals = result.away_score if prediction.favorite_side == "home" else result.home_score
            self._accumulate(
                stats,
                model.id,
                multiplier,
                odds,
                two_plus_hit=1.0 if favorite_goals >= 2 else 0.0,
                clean_sheet_hit=1.0 if underdog_goals == 0 else 0.0,
                two_plus_given_win=1.0 if multiplier > 0 and favorite_goals >= 2 else 0.0,
                clean_sheet_given_win=1.0 if multiplier > 0 and underdog_goals == 0 else 0.0,
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

    def _bully_odds(self, fixture_id: int, favorite_side: str, created_at: datetime | None) -> float | None:
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
        return snap.home_odds if favorite_side == "home" else snap.away_odds

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
