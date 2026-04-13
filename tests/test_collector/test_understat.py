import json
import pytest
import responses
from app.collector.understat import UnderstatClient, LEAGUE_UNDERSTAT_KEYS


def make_html(data: dict) -> str:
    encoded = json.dumps(data).replace("'", "\\'")
    return f"<html><script>var datesData = JSON.parse('{encoded}')</script></html>"


@responses.activate
def test_fetch_league_matches_returns_list():
    sample = [
        {"id": "1", "h": {"id": "11", "title": "Arsenal", "xG": "1.42"},
         "a": {"id": "22", "title": "Chelsea", "xG": "0.87"},
         "datetime": "2025-12-01 15:00:00", "goals": {"h": "2", "a": "1"}}
    ]
    responses.add(responses.GET, "https://understat.com/league/EPL/2025",
                  body=make_html(sample), status=200)
    client = UnderstatClient()
    matches = client.fetch_league_matches("EPL", 2025)
    assert len(matches) == 1
    assert matches[0]["h"]["title"] == "Arsenal"
    assert float(matches[0]["h"]["xG"]) == pytest.approx(1.42)


def test_league_keys_cover_all_five():
    assert set(LEAGUE_UNDERSTAT_KEYS.keys()) == {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1"}
    assert LEAGUE_UNDERSTAT_KEYS["eng.1"] == "EPL"


@responses.activate
def test_fetch_team_ppda():
    team_data = {"ppda": {"att": 456, "def": 55}}  # ppda = att/def = 8.29
    encoded = json.dumps(team_data).replace("'", "\\'")
    html = f"<html><script>var teamData = JSON.parse('{encoded}')</script></html>"
    responses.add(responses.GET, "https://understat.com/team/Arsenal/2025",
                  body=html, status=200)
    client = UnderstatClient()
    ppda = client.fetch_team_ppda("Arsenal", 2025)
    assert ppda == pytest.approx(456 / 55, rel=0.01)


@responses.activate
def test_rate_limit_respected(monkeypatch):
    import time
    calls = []
    monkeypatch.setattr(time, "sleep", lambda s: calls.append(s))
    sample = []
    responses.add(responses.GET, "https://understat.com/league/EPL/2025",
                  body=make_html(sample), status=200)
    responses.add(responses.GET, "https://understat.com/league/La_liga/2025",
                  body=make_html(sample), status=200)
    client = UnderstatClient()
    client.fetch_league_matches("EPL", 2025)
    client.fetch_league_matches("La_liga", 2025)
    assert len(calls) >= 1  # sleep called between requests
    assert all(s >= 2.0 for s in calls)
