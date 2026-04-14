import json
import re
import time
import requests

from app.collector._retry import http_retry

LEAGUE_UNDERSTAT_KEYS: dict[str, str] = {
    "eng.1": "EPL",
    "esp.1": "La_liga",
    "ger.1": "Bundesliga",
    "ita.1": "Serie_A",
    "fra.1": "Ligue_1",
}

_DATES_PATTERN = re.compile(r"var datesData\s*=\s*JSON\.parse\('(.+?)'\)", re.DOTALL)
_TEAM_PATTERN = re.compile(r"var teamData\s*=\s*JSON\.parse\('(.+?)'\)", re.DOTALL)
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Safari/537.36",
]
_DELAY_SECONDS = 2.5


class UnderstatClient:
    def __init__(self):
        self._agent_idx = 0
        self._last_request = 0.0

    @http_retry
    def _get(self, url: str) -> str:
        elapsed = time.time() - self._last_request
        if elapsed < _DELAY_SECONDS:
            time.sleep(_DELAY_SECONDS - elapsed)
        headers = {"User-Agent": _USER_AGENTS[self._agent_idx % len(_USER_AGENTS)]}
        self._agent_idx += 1
        resp = requests.get(url, headers=headers, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        self._last_request = time.time()
        return resp.text

    def fetch_league_matches(self, understat_key: str, season: int) -> list[dict]:
        url = f"https://understat.com/league/{understat_key}/{season}"
        html = self._get(url)
        m = _DATES_PATTERN.search(html)
        if not m:
            return []
        raw = m.group(1).encode().decode("unicode_escape")
        return json.loads(raw)

    def fetch_team_ppda(self, team_name: str, season: int) -> float | None:
        url = f"https://understat.com/team/{team_name}/{season}"
        html = self._get(url)
        m = _TEAM_PATTERN.search(html)
        if not m:
            return None
        raw = m.group(1).encode().decode("unicode_escape")
        data = json.loads(raw)
        ppda = data.get("ppda")
        if not ppda:
            return None
        att, def_ = ppda.get("att"), ppda.get("def")
        if not att or not def_:
            return None
        return att / def_
