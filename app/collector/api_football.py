import httpx

from app.collector._retry import http_retry

_BASE = "https://v3.football.api-sports.io"


class APIFootballClient:
    def __init__(self, api_key: str):
        self._key = api_key

    def _headers(self) -> dict:
        if not self._key:
            raise ValueError("api_football_key is not configured")
        return {"x-apisports-key": self._key}

    @http_retry
    def _get(self, path: str, params: dict) -> list:
        resp = httpx.get(f"{_BASE}/{path}", headers=self._headers(),
                         params=params, timeout=20)
        resp.raise_for_status()
        return resp.json().get("response", [])

    def fetch_lineups(self, fixture_id: int) -> list[dict]:
        return self._get("fixtures/lineups", {"fixture": fixture_id})

    def fetch_red_card_events(self, fixture_id: int) -> list[dict]:
        events = self._get("fixtures/events", {"fixture": fixture_id})
        return [e for e in events
                if e.get("type") == "Card" and e.get("detail") == "Red Card"]

    def fetch_referee(self, fixture_id: int) -> str | None:
        results = self._get("fixtures", {"id": fixture_id})
        if not results:
            return None
        return results[0].get("fixture", {}).get("referee")
