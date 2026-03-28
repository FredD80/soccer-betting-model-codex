import logging
from datetime import datetime, timezone
from app.db.models import ModelVersion, Fixture, OddsSnapshot, Result, BacktestRun
from app.models.base import BaseModel, ModelPrediction
from app.tracker import prediction_correct, get_odds_for_prediction

logger = logging.getLogger(__name__)


class _PredictionAdapter:
    """Adapts ModelPrediction to the interface expected by tracker functions."""
    def __init__(self, mp: ModelPrediction):
        self.predicted_outcome = mp.outcome
        self.bet_type = mp.bet_type
        self.line = mp.line


class Backtester:
    def __init__(self, session, model_classes: list[type[BaseModel]]):
        self.session = session
        self.model_map = {(cls.name, cls.version): cls() for cls in model_classes}

    def run(self, model_name: str, model_version: str, date_from: datetime, date_to: datetime):
        """Run a backtest for a given model over a date range.

        Writes to backtest_runs table only — never to predictions table.
        Computes per-bet-type statistics: total, correct, accuracy, ROI.
        """
        mv = self.session.query(ModelVersion).filter_by(name=model_name, version=model_version).first()
        if not mv:
            raise ValueError(f"Model {model_name}@{model_version} not registered")

        model = self.model_map.get((model_name, model_version))
        if not model:
            raise ValueError(f"Model class for {model_name}@{model_version} not provided")

        # Query all completed fixtures in the date range
        fixtures = (self.session.query(Fixture)
                    .filter(Fixture.status == "completed")
                    .filter(Fixture.kickoff_at >= date_from)
                    .filter(Fixture.kickoff_at <= date_to)
                    .all())

        # Accumulate statistics per bet_type
        bet_type_stats: dict[str, dict] = {}

        for fixture in fixtures:
            # Get latest odds snapshot for this fixture
            snap = (self.session.query(OddsSnapshot)
                    .filter_by(fixture_id=fixture.id)
                    .order_by(OddsSnapshot.captured_at.desc())
                    .first())

            # Get the result
            result = self.session.query(Result).filter_by(fixture_id=fixture.id).first()

            # Skip if missing odds or result
            if not snap or not result:
                continue

            # Call the model to get predictions
            fixture_dict = {
                "id": fixture.id,
                "home_team_id": fixture.home_team_id,
                "away_team_id": fixture.away_team_id,
                "kickoff_at": fixture.kickoff_at
            }
            odds_dict = {
                "home_odds": snap.home_odds,
                "draw_odds": snap.draw_odds,
                "away_odds": snap.away_odds,
                "ht_home_odds": snap.ht_home_odds,
                "ht_draw_odds": snap.ht_draw_odds,
                "ht_away_odds": snap.ht_away_odds,
                "total_goals_line": snap.total_goals_line,
                "over_odds": snap.over_odds,
                "under_odds": snap.under_odds,
                "ht_goals_line": snap.ht_goals_line,
                "ht_over_odds": snap.ht_over_odds,
                "ht_under_odds": snap.ht_under_odds,
            }

            predictions = model.predict(fixture_dict, odds_dict, [])

            # Evaluate each prediction and accumulate statistics
            for pred in predictions:
                stats = bet_type_stats.setdefault(pred.bet_type, {"total": 0, "correct": 0, "roi_sum": 0.0})

                adapted = _PredictionAdapter(pred)
                is_correct = prediction_correct(adapted, result)
                odds = get_odds_for_prediction(adapted, snap)

                # Calculate ROI delta for this bet
                if is_correct and odds is not None:
                    roi_delta = odds - 1
                else:
                    roi_delta = -1.0

                stats["total"] += 1
                stats["correct"] += (1 if is_correct else 0)
                stats["roi_sum"] += roi_delta

        # Create BacktestRun records for each bet_type
        for bet_type, stats in bet_type_stats.items():
            n = stats["total"]
            run = BacktestRun(
                model_id=mv.id,
                bet_type=bet_type,
                date_from=date_from,
                date_to=date_to,
                total=n,
                correct=stats["correct"],
                accuracy=stats["correct"] / n if n else 0.0,
                roi=stats["roi_sum"] / n if n else 0.0,
                run_at=datetime.now(timezone.utc),
            )
            self.session.add(run)

        self.session.commit()
        logger.info("Backtest %s@%s: %d fixtures processed", model_name, model_version, len(fixtures))
