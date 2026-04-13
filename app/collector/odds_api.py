import requests
from datetime import datetime

BASE_URL = "https://api.the-odds-api.com/v4"

LEAGUE_SPORT_KEYS = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_germany_bundesliga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_uefa_champs_league",
]


class OddsAPIClient:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def fetch_odds(self, sport_key: str) -> list[dict]:
        url = f"{BASE_URL}/sports/{sport_key}/odds/"
        params = {
            "apiKey": self.api_key,
            "regions": "us,uk",
            "markets": "h2h,totals,h2h_h1,totals_h1,spreads",
            "oddsFormat": "decimal",
        }
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        raw = response.json()
        return [self._parse_fixture(f) for f in raw]

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
        return {
            "key": bookmaker["key"],
            "title": bookmaker["title"],
            "h2h": self._parse_h2h(markets.get("h2h"), home_team, away_team),
            "totals": self._parse_totals(markets.get("totals")),
            "ht_h2h": self._parse_h2h(markets.get("h2h_h1"), home_team, away_team),
            "ht_totals": self._parse_totals(markets.get("totals_h1")),
            "spreads": self._parse_spreads(markets.get("spreads"), home_team, away_team),
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
