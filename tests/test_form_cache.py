from datetime import datetime, timezone, timedelta
import pytest
from app.db.models import League, Team, Fixture, Result, FormCache


def _seed_team_with_results(db, *, is_home: bool, scores: list[tuple[int, int]], red_card_minutes: list[int | None] = None):
    """
    Helper: create a team, opponent, and N completed fixtures with results.
    scores = list of (team_score, opponent_score) from team's perspective.
    Returns the team.
    """
    if red_card_minutes is None:
        red_card_minutes = [None] * len(scores)

    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()

    team = Team(name="Arsenal", league_id=league.id)
    opponent = Team(name="Chelsea", league_id=league.id)
    db.add_all([team, opponent])
    db.flush()

    for i, ((ts, os), rcm) in enumerate(zip(scores, red_card_minutes)):
        if is_home:
            home_id, away_id = team.id, opponent.id
            home_score, away_score = ts, os
        else:
            home_id, away_id = opponent.id, team.id
            home_score, away_score = os, ts

        f = Fixture(
            espn_id=f"fx{i}",
            home_team_id=home_id,
            away_team_id=away_id,
            league_id=league.id,
            kickoff_at=datetime.now(timezone.utc) - timedelta(days=i + 1),
            status="completed",
        )
        db.add(f)
        db.flush()

        r = Result(
            fixture_id=f.id,
            home_score=home_score,
            away_score=away_score,
            outcome="home" if home_score > away_score else ("away" if away_score > home_score else "draw"),
            total_goals=home_score + away_score,
            red_card_minute=rcm,
            verified_at=datetime.now(timezone.utc),
        )
        db.add(r)
        db.flush()

    return team


def test_form_cache_builder_computes_goals_avg(db):
    from app.form_cache import FormCacheBuilder
    team = _seed_team_with_results(db, is_home=True, scores=[(2, 1), (1, 0), (3, 2), (0, 1), (2, 0)])
    count = FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    assert cache is not None
    assert cache.matches_count == 5
    assert abs(cache.goals_scored_avg - (2 + 1 + 3 + 0 + 2) / 5) < 0.01
    assert abs(cache.goals_conceded_avg - (1 + 0 + 2 + 1 + 0) / 5) < 0.01


def test_form_cache_builder_cover_rate(db):
    from app.form_cache import FormCacheBuilder
    # 3 wins, 1 draw, 1 loss
    team = _seed_team_with_results(db, is_home=True, scores=[(2, 0), (1, 0), (0, 0), (3, 1), (0, 2)])
    FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    # 3 wins → cover_rate = 3/5 = 0.6
    assert abs(cache.spread_cover_rate - 0.6) < 0.01


def test_form_cache_builder_ou_rates(db):
    from app.form_cache import FormCacheBuilder
    # totals: 3, 4, 2, 1, 5
    team = _seed_team_with_results(db, is_home=True, scores=[(2, 1), (3, 1), (1, 1), (1, 0), (3, 2)])
    FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    # totals > 1.5: 3,4,2,5 yes; 1 no → 4/5 = 0.8
    assert abs(cache.ou_hit_rate_15 - 0.8) < 0.01
    # totals > 2.5: 3,4,5 yes; 2,1 no → 3/5 = 0.6
    assert abs(cache.ou_hit_rate_25 - 0.6) < 0.01
    # totals > 3.5: 4,5 yes; 3,2,1 no → 2/5 = 0.4
    assert abs(cache.ou_hit_rate_35 - 0.4) < 0.01


def test_form_cache_red_card_normalization_early(db):
    from app.form_cache import FormCacheBuilder
    # 5 games; game 0 has red card at minute 25 (weight 0.25)
    # weighted_scored = 3*0.25 + 1*1 + 1*1 + 2*1 + 2*1 = 0.75+1+1+2+2 = 6.75
    # total_weight = 0.25+1+1+1+1 = 4.25
    # avg = 6.75/4.25 ≈ 1.588
    team = _seed_team_with_results(
        db, is_home=True,
        scores=[(3, 0), (1, 1), (1, 2), (2, 0), (2, 1)],
        red_card_minutes=[25, None, None, None, None],
    )
    FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    assert abs(cache.goals_scored_avg - (6.75 / 4.25)) < 0.01


def test_form_cache_red_card_normalization_late(db):
    from app.form_cache import FormCacheBuilder
    # Red card at minute 70 → weight 0.75
    # weighted_scored = 2*0.75 + 1+1+2+2 = 1.5+6 = 7.5
    # total_weight = 0.75+4 = 4.75
    # avg = 7.5/4.75 ≈ 1.579
    team = _seed_team_with_results(
        db, is_home=True,
        scores=[(2, 1), (1, 0), (1, 2), (2, 0), (2, 1)],
        red_card_minutes=[70, None, None, None, None],
    )
    FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    assert abs(cache.goals_scored_avg - (7.5 / 4.75)) < 0.01


def test_form_cache_away_form_tracked_separately(db):
    from app.form_cache import FormCacheBuilder
    team = _seed_team_with_results(db, is_home=False, scores=[(1, 2), (0, 1), (2, 2)])
    FormCacheBuilder(db).build_all()
    home_cache = db.query(FormCache).filter_by(team_id=team.id, is_home=True).first()
    away_cache = db.query(FormCache).filter_by(team_id=team.id, is_home=False).first()
    assert home_cache is None  # no home results seeded
    assert away_cache is not None
    assert away_cache.matches_count == 3


def test_form_cache_no_results_skipped(db):
    from app.form_cache import FormCacheBuilder
    league = League(name="EPL", country="England", espn_id="eng.1", odds_api_key="soccer_epl")
    db.add(league)
    db.flush()
    team = Team(name="NewTeam", league_id=league.id)
    db.add(team)
    db.flush()
    count = FormCacheBuilder(db).build_all()
    cache = db.query(FormCache).filter_by(team_id=team.id).first()
    assert cache is None  # no results → no cache entry
