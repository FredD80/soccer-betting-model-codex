import logging
from datetime import datetime, timezone
from app.db.models import (
    Result, Prediction, OddsSnapshot, Performance,
    MoneylinePrediction, SpreadPrediction, OUAnalysis, PredictionOutcome, ManualPick,
)

logger = logging.getLogger(__name__)


def compute_outcome(home: int, away: int) -> str:
    if home > away:
        return "home"
    elif away > home:
        return "away"
    return "draw"


def prediction_correct(pred: Prediction, result: Result) -> bool:
    if pred.bet_type == "match_result":
        return pred.predicted_outcome == result.outcome
    if pred.bet_type == "ht_result":
        return pred.predicted_outcome == result.ht_outcome
    if pred.bet_type == "total_goals":
        if pred.line is None or result.total_goals is None:
            return False
        return (pred.predicted_outcome == "over" and result.total_goals > pred.line) or \
               (pred.predicted_outcome == "under" and result.total_goals < pred.line)
    if pred.bet_type == "ht_goals":
        if pred.line is None or result.ht_total_goals is None:
            return False
        return (pred.predicted_outcome == "over" and result.ht_total_goals > pred.line) or \
               (pred.predicted_outcome == "under" and result.ht_total_goals < pred.line)
    return False


def prediction_roi_multiplier(pred: Prediction, result: Result) -> float:
    """Returns 1.0 for win, 0.0 for push, -1.0 for loss/miss."""
    if pred.bet_type in ("match_result", "ht_result"):
        outcome = result.outcome if pred.bet_type == "match_result" else result.ht_outcome
        return 1.0 if pred.predicted_outcome == outcome else -1.0

    total = result.total_goals if pred.bet_type == "total_goals" else result.ht_total_goals
    if total is None or pred.line is None:
        return -1.0
    if total == pred.line:
        return 0.0  # push — exact line hit
    if pred.predicted_outcome == "over":
        return 1.0 if total > pred.line else -1.0
    return 1.0 if total < pred.line else -1.0


def get_odds_for_prediction(pred: Prediction, snap: OddsSnapshot) -> float | None:
    mapping = {
        ("match_result", "home"): snap.home_odds,
        ("match_result", "draw"): snap.draw_odds,
        ("match_result", "away"): snap.away_odds,
        ("ht_result", "home"): snap.ht_home_odds,
        ("ht_result", "draw"): snap.ht_draw_odds,
        ("ht_result", "away"): snap.ht_away_odds,
        ("total_goals", "over"): snap.over_odds,
        ("total_goals", "under"): snap.under_odds,
        ("ht_goals", "over"): snap.ht_over_odds,
        ("ht_goals", "under"): snap.ht_under_odds,
    }
    return mapping.get((pred.bet_type, pred.predicted_outcome))


def decimal_to_american(decimal_odds: float | None) -> int | None:
    if decimal_odds is None or decimal_odds <= 1.0:
        return None
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1.0) * 100))
    return int(round(-100.0 / (decimal_odds - 1.0)))


def _spread_result_status(team_side: str, line: float, result: Result) -> str:
    margin = (
        result.home_score - result.away_score
        if team_side == "home"
        else result.away_score - result.home_score
    )
    adjusted = margin + line
    if adjusted > 0:
        return "win"
    is_integer_line = abs(round(line) - line) < 1e-6
    if is_integer_line and adjusted == 0:
        return "push"
    return "loss"


def _ou_result_status(direction: str, line: float, result: Result) -> str:
    if result.total_goals is None:
        return "ungraded"
    if result.total_goals > line:
        return "win" if direction == "over" else "loss"
    if result.total_goals < line:
        return "win" if direction == "under" else "loss"
    return "push"


def _profit_units(result_status: str, decimal_odds: float | None, stake_units: float = 1.0) -> float | None:
    if result_status == "push":
        return 0.0
    if result_status == "loss":
        return -stake_units
    if result_status == "win":
        return ((decimal_odds - 1.0) * stake_units) if decimal_odds is not None else None
    return None


class ResultsTracker:
    def __init__(self, session):
        self.session = session

    def save_result(self, fixture_id: int, home_score: int, away_score: int,
                    ht_home_score: int | None = None, ht_away_score: int | None = None):
        ht_outcome = compute_outcome(ht_home_score, ht_away_score) if (ht_home_score is not None and ht_away_score is not None) else None
        result = Result(
            fixture_id=fixture_id,
            home_score=home_score,
            away_score=away_score,
            outcome=compute_outcome(home_score, away_score),
            ht_home_score=ht_home_score,
            ht_away_score=ht_away_score,
            ht_outcome=ht_outcome,
            total_goals=home_score + away_score,
            ht_total_goals=(ht_home_score + ht_away_score) if (ht_home_score is not None and ht_away_score is not None) else None,
            verified_at=datetime.now(timezone.utc),
        )
        self.session.add(result)
        self.session.commit()

    def evaluate_predictions(self, fixture_id: int):
        result = self.session.query(Result).filter_by(fixture_id=fixture_id).first()
        if not result:
            logger.warning("No result found for fixture %s — skipping evaluation", fixture_id)
            return
        predictions = self.session.query(Prediction).filter_by(fixture_id=fixture_id).all()

        # Guard: check if already evaluated (any performance row updated after result was verified)
        already_evaluated = False
        for pred in predictions:
            perf_existing = self.session.query(Performance).filter_by(
                model_id=pred.model_id, bet_type=pred.bet_type
            ).first()
            if (perf_existing and perf_existing.updated_at and result.verified_at
                    and perf_existing.updated_at >= result.verified_at):
                already_evaluated = True
                break

        if already_evaluated:
            logger.warning("Predictions for fixture %s already evaluated, skipping", fixture_id)
            return

        for pred in predictions:
            snap = self.session.query(OddsSnapshot).filter_by(id=pred.odds_snapshot_id).first()
            multiplier = prediction_roi_multiplier(pred, result)
            is_correct = multiplier > 0
            odds = get_odds_for_prediction(pred, snap) if snap else None
            if multiplier == 1.0 and odds is not None:
                roi_delta = odds - 1
            elif multiplier == 0.0:
                roi_delta = 0.0  # push — refund
            else:
                roi_delta = -1.0
            self._update_performance(pred.model_id, pred.bet_type, is_correct, roi_delta)
        self.session.commit()

    def settle_live_predictions(self, fixture_id: int) -> int:
        result = self.session.query(Result).filter_by(fixture_id=fixture_id).first()
        if not result:
            logger.warning("No result found for fixture %s — skipping live settlement", fixture_id)
            return 0

        settled = 0
        impacted: set[tuple[int, str]] = set()

        for pick in self.session.query(MoneylinePrediction).filter_by(fixture_id=fixture_id).all():
            self._upsert_live_outcome(
                fixture_id=fixture_id,
                model_id=pick.model_id,
                market_type="moneyline",
                prediction_row_id=pick.id,
                selection=pick.outcome,
                line=None,
                model_probability=pick.probability,
                final_probability=pick.final_probability,
                edge_pct=pick.edge_pct,
                kelly_fraction=pick.kelly_fraction,
                confidence_tier=pick.confidence_tier,
                result_status="win" if pick.outcome == result.outcome else "loss",
                decimal_odds=self._moneyline_odds(pick),
            )
            settled += 1
            impacted.add((pick.model_id, "moneyline"))

        for pick in self.session.query(SpreadPrediction).filter_by(fixture_id=fixture_id).all():
            self._upsert_live_outcome(
                fixture_id=fixture_id,
                model_id=pick.model_id,
                market_type="spread",
                prediction_row_id=pick.id,
                selection=pick.team_side,
                line=pick.goal_line,
                model_probability=pick.cover_probability,
                final_probability=pick.final_probability,
                edge_pct=pick.edge_pct,
                kelly_fraction=pick.kelly_fraction,
                confidence_tier=pick.confidence_tier,
                result_status=_spread_result_status(pick.team_side, pick.goal_line, result),
                decimal_odds=self._spread_odds(pick),
            )
            settled += 1
            impacted.add((pick.model_id, "spread"))

        for pick in self.session.query(OUAnalysis).filter_by(fixture_id=fixture_id).all():
            self._upsert_live_outcome(
                fixture_id=fixture_id,
                model_id=pick.model_id,
                market_type="ou",
                prediction_row_id=pick.id,
                selection=pick.direction,
                line=pick.line,
                model_probability=pick.probability,
                final_probability=pick.final_probability,
                edge_pct=pick.edge_pct,
                kelly_fraction=pick.kelly_fraction,
                confidence_tier=pick.confidence_tier,
                result_status=_ou_result_status(pick.direction, pick.line, result),
                decimal_odds=self._ou_odds(pick),
            )
            settled += 1
            impacted.add((pick.model_id, "ou"))

        for model_id, market_type in impacted:
            self._refresh_live_performance(model_id, market_type)

        self.session.commit()
        return settled

    def settle_manual_picks(self, fixture_id: int) -> int:
        result = self.session.query(Result).filter_by(fixture_id=fixture_id).first()
        if not result:
            logger.warning("No result found for fixture %s — skipping manual settlement", fixture_id)
            return 0

        picks = (
            self.session.query(ManualPick)
            .filter_by(fixture_id=fixture_id)
            .filter(ManualPick.result_status.in_(("open", "ungraded")))
            .all()
        )
        for pick in picks:
            status = self._manual_pick_result_status(pick, result)
            pick.result_status = status
            pick.profit_units = _profit_units(status, pick.decimal_odds, pick.stake_units)
            pick.graded_at = datetime.now(timezone.utc)

        self.session.commit()
        return len(picks)

    def _update_performance(self, model_id: int, bet_type: str, correct: bool, roi_delta: float):
        perf = self.session.query(Performance).filter_by(model_id=model_id, bet_type=bet_type).first()
        if not perf:
            perf = Performance(model_id=model_id, bet_type=bet_type,
                               total_predictions=0, correct=0, accuracy=0.0, roi=0.0)
            self.session.add(perf)
            self.session.flush()

        n = perf.total_predictions
        perf.total_predictions = n + 1
        perf.correct = perf.correct + (1 if correct else 0)
        perf.accuracy = perf.correct / perf.total_predictions
        perf.roi = ((perf.roi * n) + roi_delta) / perf.total_predictions
        perf.updated_at = datetime.now(timezone.utc)

    def _upsert_live_outcome(
        self,
        fixture_id: int,
        model_id: int,
        market_type: str,
        prediction_row_id: int,
        selection: str,
        line: float | None,
        model_probability: float | None,
        final_probability: float | None,
        edge_pct: float | None,
        kelly_fraction: float | None,
        confidence_tier: str | None,
        result_status: str,
        decimal_odds: float | None,
    ) -> None:
        existing = (
            self.session.query(PredictionOutcome)
            .filter_by(market_type=market_type, prediction_row_id=prediction_row_id)
            .first()
        )
        profit_units = _profit_units(result_status, decimal_odds)
        payload = {
            "fixture_id": fixture_id,
            "model_id": model_id,
            "market_type": market_type,
            "prediction_row_id": prediction_row_id,
            "selection": selection,
            "line": line,
            "decimal_odds": decimal_odds,
            "american_odds": decimal_to_american(decimal_odds),
            "model_probability": model_probability,
            "final_probability": final_probability,
            "edge_pct": edge_pct,
            "kelly_fraction": kelly_fraction,
            "confidence_tier": confidence_tier,
            "result_status": result_status,
            "profit_units": profit_units,
            "graded_at": datetime.now(timezone.utc),
        }
        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
            return
        self.session.add(PredictionOutcome(**payload))

    def _moneyline_odds(self, pick: MoneylinePrediction) -> float | None:
        snap = self._snapshot_by_id_or_latest(
            pick.odds_snapshot_id,
            pick.fixture_id,
            lambda q: q.filter(OddsSnapshot.home_odds.isnot(None)).filter(OddsSnapshot.away_odds.isnot(None)),
        )
        if snap is None:
            return None
        return {"home": snap.home_odds, "draw": snap.draw_odds, "away": snap.away_odds}[pick.outcome]

    def _spread_odds(self, pick: SpreadPrediction) -> float | None:
        def decorate(query):
            if pick.team_side == "home":
                return query.filter(
                    OddsSnapshot.spread_home_line == pick.goal_line,
                    OddsSnapshot.spread_home_odds.isnot(None),
                )
            return query.filter(
                OddsSnapshot.spread_away_line == pick.goal_line,
                OddsSnapshot.spread_away_odds.isnot(None),
            )

        snap = self._snapshot_by_id_or_latest(pick.odds_snapshot_id, pick.fixture_id, decorate)
        if snap is None:
            return None
        return snap.spread_home_odds if pick.team_side == "home" else snap.spread_away_odds

    def _ou_odds(self, pick: OUAnalysis) -> float | None:
        def decorate(query):
            odds_col = OddsSnapshot.over_odds if pick.direction == "over" else OddsSnapshot.under_odds
            return query.filter(
                OddsSnapshot.total_goals_line == pick.line,
                odds_col.isnot(None),
            )

        snap = self._snapshot_by_id_or_latest(pick.odds_snapshot_id, pick.fixture_id, decorate)
        if snap is None:
            return None
        return snap.over_odds if pick.direction == "over" else snap.under_odds

    def _snapshot_by_id_or_latest(self, snapshot_id: int | None, fixture_id: int, decorate_query):
        if snapshot_id is not None:
            snap = self.session.query(OddsSnapshot).filter_by(id=snapshot_id).first()
            if snap is not None:
                return snap
        query = self.session.query(OddsSnapshot).filter_by(fixture_id=fixture_id)
        query = decorate_query(query)
        return query.order_by(OddsSnapshot.captured_at.desc()).first()

    def _refresh_live_performance(self, model_id: int, market_type: str) -> None:
        rows = (
            self.session.query(PredictionOutcome)
            .filter_by(model_id=model_id, market_type=market_type)
            .filter(PredictionOutcome.result_status.in_(("win", "loss", "push")))
            .all()
        )
        perf = self.session.query(Performance).filter_by(model_id=model_id, bet_type=market_type).first()
        if not perf:
            perf = Performance(
                model_id=model_id,
                bet_type=market_type,
                total_predictions=0,
                correct=0,
                accuracy=0.0,
                roi=0.0,
            )
            self.session.add(perf)
            self.session.flush()

        total = len(rows)
        wins = sum(1 for row in rows if row.result_status == "win")
        losses = sum(1 for row in rows if row.result_status == "loss")
        roi_sum = sum((row.profit_units or 0.0) for row in rows)

        perf.total_predictions = total
        perf.correct = wins
        perf.accuracy = (wins / (wins + losses)) if (wins + losses) else 0.0
        perf.roi = (roi_sum / total) if total else 0.0
        perf.updated_at = datetime.now(timezone.utc)

    def _manual_pick_result_status(self, pick: ManualPick, result: Result) -> str:
        if pick.market_type == "moneyline":
            return "win" if pick.selection == result.outcome else "loss"
        if pick.market_type == "spread":
            if pick.line is None:
                return "ungraded"
            return _spread_result_status(pick.selection, pick.line, result)
        if pick.market_type == "ou":
            if pick.line is None:
                return "ungraded"
            return _ou_result_status(pick.selection, pick.line, result)
        return "ungraded"
