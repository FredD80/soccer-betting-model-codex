from unittest.mock import MagicMock, patch
from datetime import datetime
from app.collector.collector import DataCollector
from app.db.models import League, Team, Fixture, OddsSnapshot


def make_league(db):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    return league


def test_collect_upserts_teams(db):
    league = make_league(db)
    espn_fixtures = [{"espn_id": "e1", "kickoff_at": "2026-04-01T15:00Z",
                      "home_team": "Arsenal", "away_team": "Chelsea",
                      "status": "scheduled", "home_score": None, "away_score": None,
                      "ht_home_score": None, "ht_away_score": None}]
    collector = DataCollector(db, odds_client=MagicMock(), espn_client=MagicMock())
    collector._upsert_fixture(espn_fixtures[0], league)
    teams = db.query(Team).all()
    assert {t.name for t in teams} == {"Arsenal", "Chelsea"}


def test_collect_upserts_fixture(db):
    league = make_league(db)
    espn_fixture = {"espn_id": "e1", "kickoff_at": "2026-04-01T15:00Z",
                    "home_team": "Arsenal", "away_team": "Chelsea",
                    "status": "scheduled", "home_score": None, "away_score": None,
                    "ht_home_score": None, "ht_away_score": None}
    collector = DataCollector(db, odds_client=MagicMock(), espn_client=MagicMock())
    fixture = collector._upsert_fixture(espn_fixture, league)
    assert fixture.espn_id == "e1"
    # Run again — should not create a duplicate
    fixture2 = collector._upsert_fixture(espn_fixture, league)
    assert db.query(Fixture).count() == 1


def test_run_creates_fixture_and_odds_snapshot(db):
    league = make_league(db)

    espn_fixture = {
        "espn_id": "e1",
        "kickoff_at": "2026-04-01T15:00Z",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "status": "scheduled",
        "home_score": None,
        "away_score": None,
        "ht_home_score": None,
        "ht_away_score": None,
    }

    odds_fixture = {
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "bookmakers": [
            {
                "key": "betmgm",
                "title": "BetMGM",
                "h2h": {"home": 2.10, "draw": 3.50, "away": 3.20},
                "totals": {"line": 2.5, "over": 1.90, "under": 1.90},
                "ht_h2h": None,
                "ht_totals": None,
            }
        ],
    }

    mock_espn = MagicMock()
    mock_espn.fetch_all_leagues.return_value = {"eng.1": [espn_fixture]}

    mock_odds = MagicMock()
    mock_odds.fetch_all_leagues.return_value = {"soccer_epl": [odds_fixture]}

    collector = DataCollector(db, odds_client=mock_odds, espn_client=mock_espn)
    collector.run()

    assert db.query(Fixture).count() == 1
    assert db.query(OddsSnapshot).count() == 1


def test_save_odds_snapshot_creates_row(db):
    league = make_league(db)
    home_team = Team(name="Arsenal", league_id=league.id)
    away_team = Team(name="Chelsea", league_id=league.id)
    db.add_all([home_team, away_team])
    db.flush()
    fixture = Fixture(home_team_id=home_team.id, away_team_id=away_team.id,
                      league_id=league.id, kickoff_at=datetime(2026, 4, 1, 15, 0),
                      espn_id="e1", status="scheduled")
    db.add(fixture)
    db.flush()

    bookmaker_data = {
        "key": "betmgm", "title": "BetMGM",
        "h2h": {"home": 2.10, "draw": 3.50, "away": 3.20},
        "totals": {"line": 2.5, "over": 1.90, "under": 1.90},
        "ht_h2h": None, "ht_totals": None,
    }
    collector = DataCollector(db, odds_client=MagicMock(), espn_client=MagicMock())
    collector._save_odds_snapshot(fixture.id, bookmaker_data)
    snap = db.query(OddsSnapshot).first()
    assert snap.bookmaker == "betmgm"
    assert snap.home_odds == 2.10
    assert snap.total_goals_line == 2.5
    assert snap.ht_goals_line is None


def test_save_odds_snapshot_persists_team_total_1_5_prices(db):
    league = make_league(db)
    home_team = Team(name="Arsenal", league_id=league.id)
    away_team = Team(name="Chelsea", league_id=league.id)
    db.add_all([home_team, away_team])
    db.flush()
    fixture = Fixture(
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        league_id=league.id,
        kickoff_at=datetime(2026, 4, 1, 15, 0),
        espn_id="e-team-total",
        status="scheduled",
    )
    db.add(fixture)
    db.flush()

    bookmaker_data = {
        "key": "betmgm",
        "title": "BetMGM",
        "h2h": {"home": 2.10, "draw": 3.50, "away": 3.20},
        "totals": {"line": 2.5, "over": 1.90, "under": 1.90},
        "ht_h2h": None,
        "ht_totals": None,
        "team_totals_1_5": {
            "home": {"over": 1.42, "under": 2.75},
            "away": {"over": 3.40, "under": 1.30},
        },
    }
    collector = DataCollector(db, odds_client=MagicMock(), espn_client=MagicMock())
    collector._save_odds_snapshot(fixture.id, bookmaker_data)
    snap = db.query(OddsSnapshot).first()
    assert snap.home_team_total_1_5_over_odds == 1.42
    assert snap.home_team_total_1_5_under_odds == 2.75
    assert snap.away_team_total_1_5_over_odds == 3.40
    assert snap.away_team_total_1_5_under_odds == 1.30


def test_run_merges_event_team_totals_by_bookmaker(db):
    league = make_league(db)

    espn_fixture = {
        "espn_id": "e2",
        "kickoff_at": "2026-04-02T15:00Z",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "status": "scheduled",
        "home_score": None,
        "away_score": None,
        "ht_home_score": None,
        "ht_away_score": None,
    }

    odds_fixture = {
        "odds_api_id": "abc123",
        "home_team": "Arsenal",
        "away_team": "Chelsea",
        "bookmakers": [
            {
                "key": "betmgm",
                "title": "BetMGM",
                "h2h": {"home": 2.10, "draw": 3.50, "away": 3.20},
                "totals": {"line": 2.5, "over": 1.90, "under": 1.90},
                "ht_h2h": None,
                "ht_totals": None,
                "spreads": None,
            }
        ],
    }

    mock_espn = MagicMock()
    mock_espn.fetch_all_leagues.return_value = {"eng.1": [espn_fixture]}

    mock_odds = MagicMock()
    mock_odds.fetch_all_leagues.return_value = {"soccer_epl": [odds_fixture]}
    mock_odds.fetch_event_team_totals.return_value = {
        "bookmakers": [
            {
                "key": "betmgm",
                "team_totals_1_5": {
                    "home": {"over": 1.42, "under": 2.75},
                    "away": {"over": 3.40, "under": 1.30},
                },
            }
        ]
    }

    collector = DataCollector(db, odds_client=mock_odds, espn_client=mock_espn)
    collector.run()

    snap = db.query(OddsSnapshot).one()
    assert snap.home_team_total_1_5_over_odds == 1.42
    assert snap.away_team_total_1_5_under_odds == 1.30
