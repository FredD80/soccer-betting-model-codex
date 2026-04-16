from datetime import datetime

import requests

from app.collector._retry import http_retry

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"

LEAGUE_ESPN_IDS = [
    "eng.1",
    "esp.1",
    "ger.1",
    "ita.1",
    "fra.1",
    "por.1",
    "usa.1",
    "uefa.champions",
]


class ESPNClient:
    @http_retry
    def fetch_fixtures(
        self,
        league_id: str,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        url = f"{BASE_URL}/{league_id}/scoreboard"
        params = None
        if start_date and end_date:
            params = {"dates": f"{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}"}
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        events = response.json().get("events", [])
        return [self._parse_event(e) for e in events]

    def fetch_all_leagues(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, list[dict]]:
        return {
            lid: self.fetch_fixtures(lid, start_date=start_date, end_date=end_date)
            for lid in LEAGUE_ESPN_IDS
        }

    def _parse_event(self, event: dict) -> dict:
        competition = event["competitions"][0]
        competitors = {c["homeAway"]: c for c in competition["competitors"]}
        status_name = event["status"]["type"]["name"]
        completed = event["status"]["type"]["completed"]

        home_score = int(competitors["home"]["score"]) if completed else None
        away_score = int(competitors["away"]["score"]) if completed else None

        if completed:
            status = "completed"
        elif "IN_PROGRESS" in status_name or "HALF" in status_name:
            status = "live"
        else:
            status = "scheduled"

        return {
            "espn_id": event["id"],
            "kickoff_at": event["date"],
            "home_team": competitors["home"]["team"]["displayName"],
            "away_team": competitors["away"]["team"]["displayName"],
            "status": status,
            "home_score": home_score,
            "away_score": away_score,
            "ht_home_score": None,
            "ht_away_score": None,
        }
