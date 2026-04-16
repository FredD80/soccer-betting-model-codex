import responses as rsps
import pytest
from app.collector.odds_api import OddsAPIClient

SAMPLE_RESPONSE = [
    {
        "id": "abc123",
        "sport_key": "soccer_epl",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "commence_time": "2026-04-01T15:00:00Z",
        "bookmakers": [
            {
                "key": "betmgm",
                "title": "BetMGM",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Arsenal", "price": 2.10},
                            {"name": "Draw", "price": 3.50},
                            {"name": "Chelsea", "price": 3.20},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.90, "point": 2.5},
                            {"name": "Under", "price": 1.90, "point": 2.5},
                        ],
                    },
                ],
            }
        ],
    }
]


@rsps.activate
def test_fetch_odds_returns_parsed_fixtures():
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_RESPONSE,
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    assert len(fixtures) == 1
    assert fixtures[0]["odds_api_id"] == "abc123"
    assert fixtures[0]["home_team"] == "Arsenal"
    assert fixtures[0]["away_team"] == "Chelsea"


@rsps.activate
def test_fetch_odds_extracts_h2h_odds():
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_RESPONSE,
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    bookmaker = fixtures[0]["bookmakers"][0]
    assert bookmaker["key"] == "betmgm"
    assert bookmaker["h2h"]["home"] == 2.10
    assert bookmaker["h2h"]["draw"] == 3.50
    assert bookmaker["h2h"]["away"] == 3.20


@rsps.activate
def test_fetch_odds_extracts_totals():
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_RESPONSE,
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    bookmaker = fixtures[0]["bookmakers"][0]
    assert bookmaker["totals"]["line"] == 2.5
    assert bookmaker["totals"]["over"] == 1.90
    assert bookmaker["totals"]["under"] == 1.90


@rsps.activate
def test_fetch_odds_handles_missing_ht_markets():
    """Half-time markets are optional — not all bookmakers provide them."""
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_RESPONSE,
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    bookmaker = fixtures[0]["bookmakers"][0]
    assert bookmaker["ht_h2h"] is None
    assert bookmaker["ht_totals"] is None


@rsps.activate
def test_fetch_all_leagues_calls_each_sport_key():
    for sport_key in [
        "soccer_epl", "soccer_spain_la_liga", "soccer_germany_bundesliga",
        "soccer_italy_serie_a", "soccer_france_ligue_one",
        "soccer_portugal_primeira_liga", "soccer_usa_mls",
        "soccer_uefa_champs_league",
    ]:
        rsps.add(
            rsps.GET,
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/",
            json=[],
            status=200,
        )
    client = OddsAPIClient(api_key="testkey")
    results = client.fetch_all_leagues()
    assert len(results) == 8


SAMPLE_WITH_SPREADS = [
    {
        "id": "abc456",
        "sport_key": "soccer_epl",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "commence_time": "2026-04-01T15:00:00Z",
        "bookmakers": [
            {
                "key": "betmgm",
                "title": "BetMGM",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Arsenal", "price": 2.10},
                            {"name": "Draw", "price": 3.50},
                            {"name": "Chelsea", "price": 3.20},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": 1.90, "point": 2.5},
                            {"name": "Under", "price": 1.90, "point": 2.5},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Arsenal", "price": 1.95, "point": -0.5},
                            {"name": "Chelsea", "price": 1.85, "point": 0.5},
                        ],
                    },
                ],
            }
        ],
    }
]


@rsps.activate
def test_fetch_odds_extracts_spreads():
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_WITH_SPREADS,
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    bookmaker = fixtures[0]["bookmakers"][0]
    assert bookmaker["spreads"]["home_line"] == -0.5
    assert bookmaker["spreads"]["home_odds"] == 1.95
    assert bookmaker["spreads"]["away_line"] == 0.5
    assert bookmaker["spreads"]["away_odds"] == 1.85


@rsps.activate
def test_fetch_odds_spreads_none_when_missing():
    rsps.add(
        rsps.GET,
        "https://api.the-odds-api.com/v4/sports/soccer_epl/odds/",
        json=SAMPLE_RESPONSE,
        status=200,
    )
    client = OddsAPIClient(api_key="testkey")
    fixtures = client.fetch_odds("soccer_epl")
    bookmaker = fixtures[0]["bookmakers"][0]
    assert bookmaker["spreads"] is None
