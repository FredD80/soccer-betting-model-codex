from datetime import datetime, timezone, timedelta
from app.db.models import ModelVersion, Fixture, OddsSnapshot, Prediction, Result
from app.models.base import BaseModel, ModelPrediction


class PredictionEngine:
    def __init__(self, session, model_classes: list[type[BaseModel]], lead_hours: int | None = None):
        self.session = session
        self.model_map = {(cls.name, cls.version): cls() for cls in model_classes}
        self._lead_hours = lead_hours

    def run(self):
        active_versions = self.session.query(ModelVersion).filter_by(active=True).all()
        upcoming = self._get_upcoming_fixtures()

        for mv in active_versions:
            model = self.model_map.get((mv.name, mv.version))
            if not model:
                continue
            for fixture in upcoming:
                snap = self._latest_snapshot(fixture.id)
                if not snap:
                    continue
                history = self._get_history(fixture)
                odds_dict = self._snapshot_to_dict(snap)
                fixture_dict = self._fixture_to_dict(fixture)
                predictions = model.predict(fixture_dict, odds_dict, history)
                for pred in predictions:
                    self._save_prediction(mv.id, fixture.id, snap.id, pred)

        self.session.commit()

    def _get_upcoming_fixtures(self) -> list[Fixture]:
        if self._lead_hours is not None:
            lead = self._lead_hours
        else:
            from app.config import settings
            lead = settings.prediction_lead_hours
        cutoff = datetime.now(timezone.utc) + timedelta(hours=lead)
        return (self.session.query(Fixture)
                .filter(Fixture.status == "scheduled")
                .filter(Fixture.kickoff_at <= cutoff)
                .all())

    def _latest_snapshot(self, fixture_id: int) -> OddsSnapshot | None:
        return (self.session.query(OddsSnapshot)
                .filter_by(fixture_id=fixture_id)
                .order_by(OddsSnapshot.captured_at.desc())
                .first())

    def _get_history(self, fixture: Fixture, lookback: int = 10) -> list[dict]:
        recent = (self.session.query(Result)
                  .join(Fixture, Result.fixture_id == Fixture.id)
                  .filter(
                      (Fixture.home_team_id == fixture.home_team_id) |
                      (Fixture.away_team_id == fixture.home_team_id) |
                      (Fixture.home_team_id == fixture.away_team_id) |
                      (Fixture.away_team_id == fixture.away_team_id)
                  )
                  .order_by(Fixture.kickoff_at.desc())
                  .limit(lookback)
                  .all())
        return [self._result_to_dict(r) for r in recent]

    def _save_prediction(self, model_id: int, fixture_id: int, snap_id: int, pred: ModelPrediction):
        p = Prediction(
            model_id=model_id,
            fixture_id=fixture_id,
            bet_type=pred.bet_type,
            predicted_outcome=pred.outcome,
            confidence=pred.confidence,
            line=pred.line,
            odds_snapshot_id=snap_id,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(p)

    def _snapshot_to_dict(self, snap: OddsSnapshot) -> dict:
        return {
            "home_odds": snap.home_odds, "draw_odds": snap.draw_odds, "away_odds": snap.away_odds,
            "ht_home_odds": snap.ht_home_odds, "ht_draw_odds": snap.ht_draw_odds, "ht_away_odds": snap.ht_away_odds,
            "total_goals_line": snap.total_goals_line, "over_odds": snap.over_odds, "under_odds": snap.under_odds,
            "ht_goals_line": snap.ht_goals_line, "ht_over_odds": snap.ht_over_odds, "ht_under_odds": snap.ht_under_odds,
        }

    def _fixture_to_dict(self, fixture: Fixture) -> dict:
        return {"id": fixture.id, "home_team_id": fixture.home_team_id,
                "away_team_id": fixture.away_team_id, "league_id": fixture.league_id,
                "kickoff_at": fixture.kickoff_at}

    def _result_to_dict(self, result: Result) -> dict:
        return {"fixture_id": result.fixture_id, "outcome": result.outcome,
                "home_score": result.home_score, "away_score": result.away_score,
                "ht_outcome": result.ht_outcome, "total_goals": result.total_goals,
                "ht_total_goals": result.ht_total_goals}
