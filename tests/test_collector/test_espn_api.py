import responses as rsps
from app.collector.espn_api import ESPNClient
from datetime import datetime, timezone

SAMPLE_SCOREBOARD = {
    "events": [
        {
            "id": "espn_001",
            "date": "2026-04-01T15:00Z",
            "status": {"type": {"name": "STATUS_SCHEDULED", "completed": False}},
            "competitions": [
                {
                    "competitors": [
                        {"homeAway": "home", "team": {"displayName": "Arsenal"}, "score": "0"},
                        {"homeAway": "away", "team": {"displayName": "Chelsea"}, "score": "0"},
                    ],
                    "situation": None,
                }
            ],
        }
    ]
}

SAMPLE_COMPLETED = {
    "events": [
        {
            "id": "espn_002",
            "date": "2026-03-20T15:00Z",
            "status": {"type": {"name": "STATUS_FINAL", "completed": True}},
            "competitions": [
                {
                    "competitors": [
                        {"homeAway": "home", "team": {"displayName": "Liverpool"}, "score": "2"},
                        {"homeAway": "away", "team": {"displayName": "Everton"}, "score": "1"},
                    ],
                    "situation": None,
                }
            ],
        }
    ]
}


@rsps.activate
def test_fetch_fixtures_returns_scheduled_matches():
    rsps.add(rsps.GET, "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard",
             json=SAMPLE_SCOREBOARD, status=200)
    client = ESPNClient()
    fixtures = client.fetch_fixtures("eng.1")
    assert len(fixtures) == 1
    assert fixtures[0]["espn_id"] == "espn_001"
    assert fixtures[0]["home_team"] == "Arsenal"
    assert fixtures[0]["away_team"] == "Chelsea"
    assert fixtures[0]["status"] == "scheduled"


@rsps.activate
def test_fetch_fixtures_supports_date_window():
    rsps.add(
        rsps.GET,
        "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard?dates=20260401-20260407",
        json=SAMPLE_SCOREBOARD,
        status=200,
    )
    client = ESPNClient()
    fixtures = client.fetch_fixtures(
        "eng.1",
        start_date=datetime(2026, 4, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 4, 7, tzinfo=timezone.utc),
    )
    assert len(fixtures) == 1
    assert fixtures[0]["espn_id"] == "espn_001"


@rsps.activate
def test_fetch_fixtures_parses_completed_with_scores():
    rsps.add(rsps.GET, "https://site.api.espn.com/apis/site/v2/sports/soccer/eng.1/scoreboard",
             json=SAMPLE_COMPLETED, status=200)
    client = ESPNClient()
    fixtures = client.fetch_fixtures("eng.1")
    assert fixtures[0]["status"] == "completed"
    assert fixtures[0]["home_score"] == 2
    assert fixtures[0]["away_score"] == 1


@rsps.activate
def test_fetch_all_leagues_queries_all_six():
    for league in ["eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "por.1", "usa.1", "uefa.champions"]:
        rsps.add(rsps.GET,
                 f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard",
                 json={"events": []}, status=200)
    client = ESPNClient()
    results = client.fetch_all_leagues()
    assert set(results.keys()) == {"eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "por.1", "usa.1", "uefa.champions"}
