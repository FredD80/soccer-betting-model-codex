import pytest
import respx
import httpx
from app.collector.api_football import APIFootballClient

BASE = "https://v3.football.api-sports.io"


@respx.mock
def test_fetch_lineup_returns_players():
    respx.get(f"{BASE}/fixtures/lineups").mock(return_value=httpx.Response(200, json={
        "response": [
            {"team": {"id": 42, "name": "Arsenal"},
             "startXI": [{"player": {"id": 1, "name": "Raya", "pos": "G"}}],
             "coach": {"id": 9, "name": "Arteta"}}
        ]
    }))
    client = APIFootballClient(api_key="test-key")
    lineups = client.fetch_lineups(fixture_id=123)
    assert len(lineups) == 1
    assert lineups[0]["team"]["name"] == "Arsenal"
    assert len(lineups[0]["startXI"]) == 1


@respx.mock
def test_fetch_fixture_events_returns_red_cards():
    respx.get(f"{BASE}/fixtures/events").mock(return_value=httpx.Response(200, json={
        "response": [
            {"time": {"elapsed": 35}, "type": "Card",
             "detail": "Red Card", "team": {"id": 42}},
            {"time": {"elapsed": 70}, "type": "Goal",
             "detail": "Normal Goal", "team": {"id": 42}},
        ]
    }))
    client = APIFootballClient(api_key="test-key")
    events = client.fetch_red_card_events(fixture_id=123)
    assert len(events) == 1
    assert events[0]["time"]["elapsed"] == 35


@respx.mock
def test_fetch_referee_info():
    respx.get(f"{BASE}/fixtures").mock(return_value=httpx.Response(200, json={
        "response": [
            {"fixture": {"id": 123, "referee": "Mike Dean"}}
        ]
    }))
    client = APIFootballClient(api_key="test-key")
    referee = client.fetch_referee(fixture_id=123)
    assert referee == "Mike Dean"


def test_missing_api_key_raises():
    client = APIFootballClient(api_key="")
    with pytest.raises(ValueError, match="api_football_key"):
        client.fetch_lineups(fixture_id=1)
