import requests
from datetime import datetime
import re

from app.collector._retry import http_retry

BASE_URL = "https://api.the-odds-api.com/v4"

LEAGUE_SPORT_KEYS = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_portugal_primeira_liga",
    "soccer_usa_mls",
    "soccer_uefa_champs_league",
]


class OddsAPIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    @http_retry
    def fetch_odds(self, sport_key: str) -> list[dict]:
        url = f"{BASE_URL}/sports/{sport_key}/odds/"
        params = {
            "apiKey": self.api_key,
            "regions": "us,us2",
            "markets": "h2h,totals,spreads",
            "oddsFormat": "decimal",
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        raw = response.json()
        return [self._parse_fixture(f) for f in raw]

    @http_retry
    def fetch_event_odds(self, sport_key: str, event_id: str, markets: str, *, regions: str = "us") -> dict:
        url = f"{BASE_URL}/sports/{sport_key}/events/{event_id}/odds"
        params = {
            "apiKey": self.api_key,
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return self._parse_fixture(response.json())

    def fetch_event_team_totals(self, sport_key: str, event_id: str) -> dict:
        return self.fetch_event_odds(
            sport_key,
            event_id,
            markets="team_totals,alternate_team_totals",
        )

    def fetch_all_leagues(self) -> dict[str, list[dict]]:
        return {key: self.fetch_odds(key) for key in LEAGUE_SPORT_KEYS}

    def _parse_fixture(self, raw: dict) -> dict:
        return {
            "odds_api_id": raw["id"],
            "sport_key": raw["sport_key"],
            "home_team": raw["home_team"],
            "away_team": raw["away_team"],
            "commence_time": raw["commence_time"],
            "bookmakers": [self._parse_bookmaker(b, raw["home_team"], raw["away_team"]) for b in raw.get("bookmakers", [])],
        }

    def _parse_bookmaker(self, bookmaker: dict, home_team: str, away_team: str) -> dict:
        markets = {m["key"]: m for m in bookmaker.get("markets", [])}
        team_total_markets = [
            market
            for market in bookmaker.get("markets", [])
            if market.get("key") in {"team_totals", "alternate_team_totals"}
        ]
        return {
            "key": bookmaker["key"],
            "title": bookmaker["title"],
            "h2h": self._parse_h2h(markets.get("h2h"), home_team, away_team),
            "totals": self._parse_totals(markets.get("totals")),
            "ht_h2h": self._parse_h2h(markets.get("h2h_h1"), home_team, away_team),
            "ht_totals": self._parse_totals(markets.get("totals_h1")),
            "spreads": self._parse_spreads(markets.get("spreads"), home_team, away_team),
            "team_totals_1_5": self._parse_team_totals_1_5(team_total_markets, home_team, away_team),
        }

    def _parse_h2h(self, market: dict | None, home_team: str, away_team: str) -> dict | None:
        if not market:
            return None
        outcomes = {o["name"]: o["price"] for o in market["outcomes"]}
        return {
            "home": outcomes.get(home_team),
            "draw": outcomes.get("Draw"),
            "away": outcomes.get(away_team),
        }

    def _parse_spreads(self, market: dict | None, home_team: str, away_team: str) -> dict | None:
        if not market:
            return None
        outcomes = {o["name"]: o for o in market["outcomes"]}
        home = outcomes.get(home_team, {})
        away = outcomes.get(away_team, {})
        return {
            "home_line": home.get("point"),
            "home_odds": home.get("price"),
            "away_line": away.get("point"),
            "away_odds": away.get("price"),
        }

    def _parse_totals(self, market: dict | None) -> dict | None:
        if not market:
            return None
        outcomes = {o["name"]: o for o in market["outcomes"]}
        over = outcomes.get("Over", {})
        return {
            "line": over.get("point"),
            "over": over.get("price"),
            "under": outcomes.get("Under", {}).get("price"),
        }

    def _parse_team_totals_1_5(
        self,
        markets: list[dict],
        home_team: str,
        away_team: str,
    ) -> dict | None:
        if not markets:
            return None

        result = {
            "home": {"over": None, "under": None},
            "away": {"over": None, "under": None},
        }

        for market in markets:
            for outcome in market.get("outcomes", []):
                point = outcome.get("point")
                if point is None:
                    continue
                try:
                    point_value = float(point)
                except (TypeError, ValueError):
                    continue
                if abs(point_value - 1.5) > 1e-9:
                    continue

                side = self._team_total_side(outcome)
                team_side = self._team_total_team(outcome, home_team, away_team)
                if side is None or team_side is None:
                    continue
                result[team_side][side] = outcome.get("price")

        if all(result[side][direction] is None for side in ("home", "away") for direction in ("over", "under")):
            return None
        return result

    def _team_total_side(self, outcome: dict) -> str | None:
        for field in ("name", "description"):
            value = outcome.get(field)
            if not value:
                continue
            label = str(value).strip().lower()
            if label.startswith("over"):
                return "over"
            if label.startswith("under"):
                return "under"
        return None

    def _team_total_team(self, outcome: dict, home_team: str, away_team: str) -> str | None:
        for field in ("description", "name"):
            value = outcome.get(field)
            if not value:
                continue
            matched = self._match_team_label(str(value), home_team, away_team)
            if matched is not None:
                return matched
        return None

    def _match_team_label(self, value: str, home_team: str, away_team: str) -> str | None:
        label = self._normalize_label(value)
        home = self._normalize_label(home_team)
        away = self._normalize_label(away_team)
        if home and (label == home or home in label):
            return "home"
        if away and (label == away or away in label):
            return "away"
        return None

    def _normalize_label(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
