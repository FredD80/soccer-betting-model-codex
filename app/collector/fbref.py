import time
import requests
from bs4 import BeautifulSoup

_DELAY_SECONDS = 3.0
_UCL_SCHEDULE_URL = (
    "https://fbref.com/en/comps/8/schedule/Champions-League-Scores-and-Fixtures"
)
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/537.36"


class FBrefClient:
    def __init__(self):
        self._last_request = 0.0

    def _get(self, url: str) -> str:
        elapsed = time.time() - self._last_request
        if elapsed < _DELAY_SECONDS:
            time.sleep(_DELAY_SECONDS - elapsed)
        resp = requests.get(url, headers={"User-Agent": _USER_AGENT},
                            timeout=30, allow_redirects=True)
        resp.raise_for_status()
        self._last_request = time.time()
        return resp.text

    def fetch_ucl_fixtures(self, season: int) -> list[dict]:
        html = self._get(_UCL_SCHEDULE_URL)
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", id="sched_all")
        if not table:
            return []
        results = []
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 5:
                continue
            date_str = cells[0].get_text(strip=True)
            home = cells[1].get_text(strip=True)
            home_xg_str = cells[2].get_text(strip=True)
            away = cells[3].get_text(strip=True)
            away_xg_str = cells[4].get_text(strip=True)
            if not home_xg_str or not away_xg_str:
                continue
            try:
                results.append({
                    "date": date_str,
                    "home": home,
                    "home_xg": float(home_xg_str),
                    "away": away,
                    "away_xg": float(away_xg_str),
                })
            except ValueError:
                continue
        return results
