# tests/test_models/test_base.py
import pytest
from app.models.base import BaseModel, ModelPrediction

BET_TYPES = ["match_result", "ht_result", "total_goals", "ht_goals"]
RESULT_OUTCOMES = ["home", "draw", "away"]
GOALS_OUTCOMES = ["over", "under"]


class ConcreteModel(BaseModel):
    name = "test_model"
    version = "1.0"

    def predict(self, fixture, odds, history):
        return [
            ModelPrediction(bet_type="match_result", outcome="home", confidence=0.65, line=None),
            ModelPrediction(bet_type="total_goals", outcome="over", confidence=0.55, line=2.5),
        ]


def test_concrete_model_returns_predictions():
    model = ConcreteModel()
    preds = model.predict({}, {}, [])
    assert len(preds) == 2


def test_prediction_bet_types_are_valid():
    model = ConcreteModel()
    preds = model.predict({}, {}, [])
    for pred in preds:
        assert pred.bet_type in BET_TYPES


def test_prediction_outcomes_are_valid():
    model = ConcreteModel()
    preds = model.predict({}, {}, [])
    for pred in preds:
        if pred.bet_type in ("match_result", "ht_result"):
            assert pred.outcome in RESULT_OUTCOMES
        else:
            assert pred.outcome in GOALS_OUTCOMES


def test_prediction_confidence_is_between_0_and_1():
    model = ConcreteModel()
    preds = model.predict({}, {}, [])
    for pred in preds:
        assert 0.0 <= pred.confidence <= 1.0


def test_model_without_predict_raises():
    with pytest.raises(TypeError):
        class BadModel(BaseModel):
            name = "bad"
            version = "1.0"
        BadModel()


def test_prediction_rejects_invalid_bet_type():
    with pytest.raises(ValueError, match="Invalid bet_type"):
        ModelPrediction(bet_type="invalid", outcome="home", confidence=0.5, line=None)


def test_prediction_rejects_confidence_out_of_range():
    with pytest.raises(ValueError, match="confidence"):
        ModelPrediction(bet_type="match_result", outcome="home", confidence=1.5, line=None)


def test_prediction_rejects_line_on_result_bet():
    with pytest.raises(ValueError, match="line must be None"):
        ModelPrediction(bet_type="match_result", outcome="home", confidence=0.5, line=2.5)


def test_prediction_requires_line_on_goals_bet():
    with pytest.raises(ValueError, match="line is required"):
        ModelPrediction(bet_type="total_goals", outcome="over", confidence=0.5, line=None)


def test_base_model_subclass_missing_name_raises():
    with pytest.raises(TypeError, match="name"):
        class NoName(BaseModel):
            version = "1.0"
            def predict(self, fixture, odds, history):
                return []
        NoName()
