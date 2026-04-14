"""Backfill historical fixtures + results from ESPN into the DB.

Usage (inside a container or venv with PYTHONPATH=/app):
    python scripts/backfill_results.py --months 6
    python scripts/backfill_results.py --leagues eng.1,esp.1 --months 12

Fetches past completed matches via ESPN's scoreboard endpoint with a
date-range query (?dates=YYYYMMDD-YYYYMMDD), upserts Team and Fixture
rows, and inserts Result rows with final scores. Idempotent — existing
results are skipped.

The form-cache builder then has enough history to produce predictions
for upcoming fixtures on a cold-start deployment.
"""
import argparse
import logging
import time
from datetime import datetime, timedelta, timezone

import requests

from app.db.connection import get_session
from app.db.models import Fixture, League, Result, Team
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"
DEFAULT_LEAGUES = ["eng.1", "esp.1", "ger.1", "ita.1", "fra.1", "uefa.champions"]


def _fetch_month(league_espn_id: str, start: datetime, end: datetime) -> list[dict]:
    url = f"{ESPN_BASE}/{league_espn_id}/scoreboard"
    params = {"dates": f"{start.strftime('%Y%m%d')}-{end.strftime('%Y%m%d')}"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("events", [])


def _parse_event(event: dict) -> dict | None:
    if not event["status"]["type"]["completed"]:
        return None
    c = event["competitions"][0]
    home = next((x for x in c["competitors"] if x["homeAway"] == "home"), None)
    away = next((x for x in c["competitors"] if x["homeAway"] == "away"), None)
    if not home or not away:
        return None
    try:
        home_score = int(home["score"])
        away_score = int(away["score"])
    except (KeyError, ValueError, TypeError):
        return None
    return {
        "espn_id": event["id"],
        "kickoff_at": datetime.fromisoformat(event["date"].replace("Z", "+00:00")),
        "home_team": home["team"]["displayName"],
        "away_team": away["team"]["displayName"],
        "home_score": home_score,
        "away_score": away_score,
    }


def _upsert_team(session, name: str, league_id: int) -> Team:
    team = session.query(Team).filter_by(name=name, league_id=league_id).first()
    if not team:
        team = Team(name=name, league_id=league_id)
        session.add(team)
        session.flush()
    return team


def _compute_outcome(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home"
    if away_score > home_score:
        return "away"
    return "draw"


def _upsert_fixture_and_result(session, parsed: dict, league: League) -> bool:
    """Returns True if a new Result was written."""
    home = _upsert_team(session, parsed["home_team"], league.id)
    away = _upsert_team(session, parsed["away_team"], league.id)

    fixture = session.query(Fixture).filter_by(espn_id=parsed["espn_id"]).first()
    if not fixture:
        fixture = Fixture(
            espn_id=parsed["espn_id"],
            home_team_id=home.id,
            away_team_id=away.id,
            league_id=league.id,
            kickoff_at=parsed["kickoff_at"],
            status="completed",
        )
        session.add(fixture)
        session.flush()
    else:
        fixture.status = "completed"

    if session.query(Result).filter_by(fixture_id=fixture.id).first():
        return False

    result = Result(
        fixture_id=fixture.id,
        home_score=parsed["home_score"],
        away_score=parsed["away_score"],
        outcome=_compute_outcome(parsed["home_score"], parsed["away_score"]),
        total_goals=parsed["home_score"] + parsed["away_score"],
        verified_at=datetime.now(timezone.utc),
    )
    session.add(result)
    return True


def run(months: int, leagues: list[str]) -> None:
    session = get_session()
    try:
        now = datetime.now(timezone.utc)
        total_new = 0
        for espn_id in leagues:
            league = session.query(League).filter_by(espn_id=espn_id).first()
            if not league:
                logger.warning("league %s not seeded, skipping", espn_id)
                continue
            league_new = 0
            for m in range(months):
                end = now - timedelta(days=m * 30)
                start = end - timedelta(days=30)
                events = _fetch_month(espn_id, start, end)
                for ev in events:
                    parsed = _parse_event(ev)
                    if not parsed:
                        continue
                    if _upsert_fixture_and_result(session, parsed, league):
                        league_new += 1
                time.sleep(0.5)  # be nice to ESPN
            session.commit()
            logger.info("league=%s wrote %d new results", espn_id, league_new)
            total_new += league_new
        logger.info("backfill complete: %d new results across %d leagues",
                    total_new, len(leagues))
    finally:
        session.close()


def main() -> None:
    configure_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--months", type=int, default=6)
    p.add_argument("--leagues", default=",".join(DEFAULT_LEAGUES))
    args = p.parse_args()
    run(args.months, args.leagues.split(","))


if __name__ == "__main__":
    main()
