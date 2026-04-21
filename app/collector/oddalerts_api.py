from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

import requests

from app.collector._retry import http_retry

BASE_URL = "https://data.oddalerts.com/api"


class OddAlertsClient:
    def __init__(self, api_token: str):
        if not api_token:
            raise ValueError("OddAlerts API token is required")
        self.api_token = api_token

    @http_retry
    def _get(self, path: str, **params) -> dict | list:
        query = {"api_token": self.api_token, **params}
        response = requests.get(f"{BASE_URL}{path}", params=query, timeout=30)
        response.raise_for_status()
        return response.json()

    def search_competitions(self, query: str, *, include: str | None = None, page: int = 1) -> dict:
        params: dict[str, object] = {"query": query, "page": page}
        if include:
            params["include"] = include
        return self._get("/competitions/search", **params)

    def fetch_fixture(self, fixture_id: int, *, include: str | None = None) -> dict:
        params: dict[str, object] = {}
        if include:
            params["include"] = include
        return self._get(f"/fixtures/{fixture_id}", **params)

    def fixtures_between(
        self,
        *,
        from_unix: int,
        to_unix: int,
        competitions: Iterable[int] | None = None,
        seasons: Iterable[int] | None = None,
        include: str | None = None,
        page: int = 1,
    ) -> dict:
        params: dict[str, object] = {
            "from": from_unix,
            "to": to_unix,
            "page": page,
        }
        if competitions:
            params["competitions"] = ",".join(str(value) for value in competitions)
        if seasons:
            params["seasons"] = ",".join(str(value) for value in seasons)
        if include:
            params["include"] = include
        return self._get("/fixtures/between", **params)

    def iter_fixtures_between(
        self,
        *,
        from_dt: datetime,
        to_dt: datetime,
        competitions: Iterable[int] | None = None,
        seasons: Iterable[int] | None = None,
        include: str | None = None,
    ) -> list[dict]:
        from_unix = int(from_dt.astimezone(timezone.utc).timestamp())
        to_unix = int(to_dt.astimezone(timezone.utc).timestamp())
        page = 1
        fixtures: list[dict] = []

        while True:
            payload = self.fixtures_between(
                from_unix=from_unix,
                to_unix=to_unix,
                competitions=competitions,
                seasons=seasons,
                include=include,
                page=page,
            )
            batch = payload.get("data", [])
            fixtures.extend(batch)
            info = payload.get("info", {})
            total_pages = int(info.get("total_pages") or 0)
            if page >= total_pages or not batch:
                break
            page += 1

        return fixtures

    def odds_history_multiple(
        self,
        fixture_ids: Iterable[int],
        *,
        markets: Iterable[int] | None = None,
        bookmakers: Iterable[int] | None = None,
    ) -> dict:
        ids = [int(value) for value in fixture_ids]
        if not ids:
            return {"info": {"count": 0}, "data": []}
        if len(ids) > 50:
            raise ValueError("OddAlerts odds/history/multiple currently supports up to 50 fixture ids")

        params: dict[str, object] = {"ids": ",".join(str(value) for value in ids)}
        if markets:
            params["markets"] = ",".join(str(value) for value in markets)
        if bookmakers:
            params["bookmakers"] = ",".join(str(value) for value in bookmakers)
        return self._get("/odds/history/multiple", **params)

    def fetch_odds_markets(self) -> list[dict]:
        payload = self._get("/odds/markets")
        if not isinstance(payload, list):
            raise ValueError("Unexpected odds/markets response")
        return payload
