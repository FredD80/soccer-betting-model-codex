from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ModelPrediction:
    bet_type: str    # "match_result" | "ht_result" | "total_goals" | "ht_goals"
    outcome: str     # match_result/ht_result: "home"|"draw"|"away"  |  total_goals/ht_goals: "over"|"under"
    confidence: float  # 0.0 – 1.0
    line: float | None  # goals line for over/under bets; None for result bets


class BaseModel(ABC):
    name: str
    version: str

    @abstractmethod
    def predict(self, fixture: dict, odds: dict, history: list[dict]) -> list[ModelPrediction]:
        """
        fixture  — dict with keys: id, home_team, away_team, league, kickoff_at
        odds     — latest OddsSnapshot as dict (all bet types included)
        history  — list of recent Result dicts for both teams (configurable lookback)
        Returns a list of ModelPrediction — model may return one or all bet types.
        """
        ...
