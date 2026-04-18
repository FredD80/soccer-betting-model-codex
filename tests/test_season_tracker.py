from datetime import date, datetime, timezone

from app.db.models import Fixture, League, Team, WeeklyModelPick
from app.season_tracker import SnapshotCandidate, snapshot_model_week


def _fixture(db, league: League, home: Team, away: Team, espn_id: str, kickoff_at: datetime) -> Fixture:
    fixture = Fixture(
        espn_id=espn_id,
        home_team_id=home.id,
        away_team_id=away.id,
        league_id=league.id,
        kickoff_at=kickoff_at,
        status="scheduled",
    )
    db.add(fixture)
    db.flush()
    return fixture


def test_snapshot_model_week_skips_duplicate_team_candidates(db, monkeypatch):
    league = League(name="Premier League", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()

    teams = []
    for idx in range(12):
        team = Team(name=f"Team {idx + 1}", league_id=league.id)
        db.add(team)
        teams.append(team)
    db.flush()

    kickoff = datetime(2026, 4, 20, 15, 0, tzinfo=timezone.utc)
    fixtures = [
        _fixture(db, league, teams[0], teams[1], "mw-1", kickoff),
        _fixture(db, league, teams[0], teams[2], "mw-2", kickoff.replace(hour=18)),
        _fixture(db, league, teams[3], teams[4], "mw-3", kickoff.replace(day=21)),
        _fixture(db, league, teams[5], teams[6], "mw-4", kickoff.replace(day=22)),
        _fixture(db, league, teams[7], teams[8], "mw-5", kickoff.replace(day=23)),
        _fixture(db, league, teams[9], teams[10], "mw-6", kickoff.replace(day=24)),
        _fixture(db, league, teams[1], teams[11], "mw-7", kickoff.replace(day=25)),
    ]

    def build_candidates(_session, *, model_view: str, week_start: date) -> list[SnapshotCandidate]:
        return [
            SnapshotCandidate(
                fixture_id=fixtures[0].id,
                league_id=league.id,
                home_team_id=fixtures[0].home_team_id,
                away_team_id=fixtures[0].away_team_id,
                kickoff_at=fixtures[0].kickoff_at,
                model_id=None,
                market_type="moneyline",
                selection="home",
                line=None,
                decimal_odds=1.8,
                american_odds=-125,
                model_probability=0.62,
                final_probability=0.62,
                edge_pct=0.06,
                confidence_tier="HIGH",
            ),
            SnapshotCandidate(
                fixture_id=fixtures[1].id,
                league_id=league.id,
                home_team_id=fixtures[1].home_team_id,
                away_team_id=fixtures[1].away_team_id,
                kickoff_at=fixtures[1].kickoff_at,
                model_id=None,
                market_type="moneyline",
                selection="home",
                line=None,
                decimal_odds=1.85,
                american_odds=-118,
                model_probability=0.61,
                final_probability=0.61,
                edge_pct=0.05,
                confidence_tier="HIGH",
            ),
            SnapshotCandidate(
                fixture_id=fixtures[2].id,
                league_id=league.id,
                home_team_id=fixtures[2].home_team_id,
                away_team_id=fixtures[2].away_team_id,
                kickoff_at=fixtures[2].kickoff_at,
                model_id=None,
                market_type="moneyline",
                selection="home",
                line=None,
                decimal_odds=1.9,
                american_odds=-111,
                model_probability=0.6,
                final_probability=0.6,
                edge_pct=0.04,
                confidence_tier="HIGH",
            ),
            SnapshotCandidate(
                fixture_id=fixtures[3].id,
                league_id=league.id,
                home_team_id=fixtures[3].home_team_id,
                away_team_id=fixtures[3].away_team_id,
                kickoff_at=fixtures[3].kickoff_at,
                model_id=None,
                market_type="moneyline",
                selection="home",
                line=None,
                decimal_odds=1.92,
                american_odds=-109,
                model_probability=0.59,
                final_probability=0.59,
                edge_pct=0.03,
                confidence_tier="HIGH",
            ),
            SnapshotCandidate(
                fixture_id=fixtures[4].id,
                league_id=league.id,
                home_team_id=fixtures[4].home_team_id,
                away_team_id=fixtures[4].away_team_id,
                kickoff_at=fixtures[4].kickoff_at,
                model_id=None,
                market_type="moneyline",
                selection="home",
                line=None,
                decimal_odds=1.95,
                american_odds=-105,
                model_probability=0.58,
                final_probability=0.58,
                edge_pct=0.02,
                confidence_tier="HIGH",
            ),
            SnapshotCandidate(
                fixture_id=fixtures[5].id,
                league_id=league.id,
                home_team_id=fixtures[5].home_team_id,
                away_team_id=fixtures[5].away_team_id,
                kickoff_at=fixtures[5].kickoff_at,
                model_id=None,
                market_type="moneyline",
                selection="home",
                line=None,
                decimal_odds=2.0,
                american_odds=100,
                model_probability=0.57,
                final_probability=0.57,
                edge_pct=0.01,
                confidence_tier="HIGH",
            ),
            SnapshotCandidate(
                fixture_id=fixtures[6].id,
                league_id=league.id,
                home_team_id=fixtures[6].home_team_id,
                away_team_id=fixtures[6].away_team_id,
                kickoff_at=fixtures[6].kickoff_at,
                model_id=None,
                market_type="moneyline",
                selection="home",
                line=None,
                decimal_odds=2.02,
                american_odds=102,
                model_probability=0.56,
                final_probability=0.56,
                edge_pct=0.01,
                confidence_tier="HIGH",
            ),
        ]

    monkeypatch.setattr("app.season_tracker.build_weekly_candidates", build_candidates)

    created = snapshot_model_week(db, season_key="2025-26", week_start=date(2026, 4, 20))
    assert created == 15

    main_rows = (
        db.query(WeeklyModelPick)
        .filter_by(season_key="2025-26", week_start=date(2026, 4, 20), model_view="main")
        .order_by(WeeklyModelPick.rank.asc())
        .all()
    )
    assert len(main_rows) == 5
    assert [row.fixture_id for row in main_rows] == [
        fixtures[0].id,
        fixtures[2].id,
        fixtures[3].id,
        fixtures[4].id,
        fixtures[5].id,
    ]
    assert fixtures[1].id not in {row.fixture_id for row in main_rows}
