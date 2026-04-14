from datetime import datetime, timezone, timedelta

import numpy as np
import pytest

from app.db.models import League, Team, Fixture, FormCache, Result, MLArtifact
from scripts.train_ml_lambda import (
    train, InsufficientDataError, BaselineRegressionError,
)


def _seed(db, n):
    lg = League(name="EPL", country="E", espn_id="eng.1", odds_api_key="x")
    db.add(lg); db.flush()
    teams = []
    for i in range(10):
        t = Team(name=f"T{i}", league_id=lg.id); db.add(t); teams.append(t)
    db.flush()
    for i in range(n):
        h = teams[i % 10]; a = teams[(i + 1) % 10]
        if h.id == a.id:
            continue
        f = Fixture(home_team_id=h.id, away_team_id=a.id, league_id=lg.id,
                    kickoff_at=datetime.now(timezone.utc) - timedelta(days=i),
                    status="completed")
        db.add(f); db.flush()
        db.add(Result(fixture_id=f.id, home_score=np.random.poisson(1.5),
                      away_score=np.random.poisson(1.1), total_goals=3))
    # minimal form cache for heuristic baseline
    for t in teams:
        db.add(FormCache(team_id=t.id, is_home=True, goals_scored_avg=1.3,
                         goals_conceded_avg=1.2, matches_count=5))
        db.add(FormCache(team_id=t.id, is_home=False, goals_scored_avg=1.1,
                         goals_conceded_avg=1.4, matches_count=5))
    db.flush()


def test_insufficient_data_raises(db, tmp_path):
    _seed(db, 20)
    with pytest.raises(InsufficientDataError):
        train(db, output_dir=tmp_path, min_samples=500)


def test_trains_and_registers_artifact(db, tmp_path):
    np.random.seed(0)
    _seed(db, 600)
    path = train(db, output_dir=tmp_path, min_samples=100, check_baseline=False)
    assert path.exists()
    rows = db.query(MLArtifact).filter_by(active=True).all()
    assert len(rows) == 1
    assert rows[0].name == "ml_lambda"


def test_deactivates_previous_artifacts(db, tmp_path):
    np.random.seed(0)
    _seed(db, 600)
    db.add(MLArtifact(name="ml_lambda", version="old", path="/tmp/old.pkl",
                      active=True, trained_at=datetime.now(timezone.utc)))
    db.flush()
    train(db, output_dir=tmp_path, min_samples=100, check_baseline=False)
    active = db.query(MLArtifact).filter_by(active=True).all()
    assert len(active) == 1
    assert active[0].version != "old"
