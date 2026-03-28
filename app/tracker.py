from datetime import datetime, timezone
from app.db.models import Fixture, Result, Prediction, OddsSnapshot, Performance


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


class ResultsTracker:
    def __init__(self, session):
        self.session = session

    def save_result(self, fixture_id: int, home_score: int, away_score: int,
                    ht_home_score: int | None = None, ht_away_score: int | None = None):
        ht_outcome = compute_outcome(ht_home_score, ht_away_score) if ht_home_score is not None else None
        result = Result(
            fixture_id=fixture_id,
            home_score=home_score,
            away_score=away_score,
            outcome=compute_outcome(home_score, away_score),
            ht_home_score=ht_home_score,
            ht_away_score=ht_away_score,
            ht_outcome=ht_outcome,
            total_goals=home_score + away_score,
            ht_total_goals=(ht_home_score + ht_away_score) if ht_home_score is not None else None,
            verified_at=datetime.now(timezone.utc),
        )
        self.session.add(result)
        self.session.commit()

    def evaluate_predictions(self, fixture_id: int):
        result = self.session.query(Result).filter_by(fixture_id=fixture_id).first()
        if not result:
            return
        predictions = self.session.query(Prediction).filter_by(fixture_id=fixture_id).all()
        for pred in predictions:
            snap = self.session.query(OddsSnapshot).filter_by(id=pred.odds_snapshot_id).first()
            is_correct = prediction_correct(pred, result)
            odds = get_odds_for_prediction(pred, snap) if snap else None
            roi_delta = (odds - 1) if (is_correct and odds) else -1.0
            self._update_performance(pred.model_id, pred.bet_type, is_correct, roi_delta)
        self.session.commit()

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
