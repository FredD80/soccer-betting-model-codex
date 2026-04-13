import pytest
import responses
from app.collector.fbref import FBrefClient

UCL_FIXTURES_URL = "https://fbref.com/en/comps/8/schedule/Champions-League-Scores-and-Fixtures"


def _make_table_html(rows: list[dict]) -> str:
    header = "<tr><th>Date</th><th>Home</th><th>xG</th><th>Away</th><th>xG.1</th></tr>"
    body = ""
    for r in rows:
        body += f"<tr><td>{r['date']}</td><td>{r['home']}</td><td>{r['home_xg']}</td><td>{r['away']}</td><td>{r['away_xg']}</td></tr>"
    return f"<html><body><table id='sched_all'>{header}{body}</table></body></html>"


@responses.activate
def test_fetch_ucl_fixtures():
    html = _make_table_html([
        {"date": "2025-11-05", "home": "Arsenal", "home_xg": "2.10",
         "away": "PSG", "away_xg": "0.87"}
    ])
    responses.add(responses.GET, UCL_FIXTURES_URL, body=html, status=200)
    client = FBrefClient()
    fixtures = client.fetch_ucl_fixtures(season=2025)
    assert len(fixtures) == 1
    assert fixtures[0]["home"] == "Arsenal"
    assert fixtures[0]["home_xg"] == pytest.approx(2.10)


@responses.activate
def test_fetch_ucl_fixtures_skips_rows_without_xg():
    html = _make_table_html([
        {"date": "2025-11-05", "home": "Arsenal", "home_xg": "",
         "away": "PSG", "away_xg": ""},  # future fixture, no xG yet
    ])
    responses.add(responses.GET, UCL_FIXTURES_URL, body=html, status=200)
    client = FBrefClient()
    fixtures = client.fetch_ucl_fixtures(season=2025)
    assert len(fixtures) == 0  # empty xG rows skipped
