import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass


_RESULT_BET_TYPES = frozenset({"match_result", "ht_result"})
_GOALS_BET_TYPES = frozenset({"total_goals", "ht_goals"})
_VALID_BET_TYPES = _RESULT_BET_TYPES | _GOALS_BET_TYPES
_RESULT_OUTCOMES = frozenset({"home", "draw", "away"})
_GOALS_OUTCOMES = frozenset({"over", "under"})


@dataclass
class ModelPrediction:
    bet_type: str    # "match_result" | "ht_result" | "total_goals" | "ht_goals"
    outcome: str     # match_result/ht_result: "home"|"draw"|"away"  |  total_goals/ht_goals: "over"|"under"
    confidence: float  # 0.0 – 1.0
    line: float | None  # goals line for over/under bets; None for result bets

    def __post_init__(self):
        if self.bet_type not in _VALID_BET_TYPES:
            raise ValueError(f"Invalid bet_type: {self.bet_type!r}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {self.confidence}")
        if self.bet_type in _RESULT_BET_TYPES:
            if self.outcome not in _RESULT_OUTCOMES:
                raise ValueError(f"outcome {self.outcome!r} invalid for {self.bet_type}")
            if self.line is not None:
                raise ValueError(f"line must be None for {self.bet_type}")
        else:
            if self.outcome not in _GOALS_OUTCOMES:
                raise ValueError(f"outcome {self.outcome!r} invalid for {self.bet_type}")
            if self.line is None:
                raise ValueError(f"line is required for {self.bet_type}")


class BaseModel(ABC):
    name: str
    version: str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if not inspect.isabstract(cls):
            if not isinstance(getattr(cls, "name", None), str):
                raise TypeError(f"{cls.__name__} must define a class attribute 'name: str'")
            if not isinstance(getattr(cls, "version", None), str):
                raise TypeError(f"{cls.__name__} must define a class attribute 'version: str'")

    @abstractmethod
    def predict(self, fixture: dict, odds: dict, history: list[dict]) -> list[ModelPrediction]:
        """
        fixture  — dict with keys: id, home_team, away_team, league, kickoff_at
        odds     — latest OddsSnapshot as dict (all bet types included)
        history  — list of recent Result dicts for both teams (configurable lookback)
        Returns a list of ModelPrediction — model may return one or all bet types.
        """
        ...
