#!/usr/bin/env python3
"""
Backfill historical fixtures, results, and ML + totals odds from
football-data.co.uk across 2023-24, 2024-25, and 2025-26 seasons.

For each CSV row the script will:
  * resolve (or auto-create) Home / Away Team rows,
  * find an existing Fixture (by league + teams + date ±1 day) or create one,
  * upsert a Result from FTHG/FTAG/FTR + HTHG/HTAG/HTR,
  * write a single OddsSnapshot (bookmaker="bet365_historical") at kickoff-1h.

Covers EPL, La Liga, Bundesliga, Serie A, Ligue 1.

Usage:
    DATABASE_URL=postgresql://... .venv/bin/python3 scripts/backfill_odds_football_data.py              # dry-run all seasons
    DATABASE_URL=postgresql://... .venv/bin/python3 scripts/backfill_odds_football_data.py --apply      # write rows
    DATABASE_URL=postgresql://... .venv/bin/python3 scripts/backfill_odds_football_data.py --seasons 2324 2425 --apply
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta
from typing import Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ODDS_API_KEY", "dummy")
os.environ.setdefault("DATABASE_URL", "postgresql://betuser:betpass@127.0.0.1:5433/sbmdb")

from app.db.connection import get_session
from app.db.models import Fixture, League, OddsSnapshot, Result, Team

DEFAULT_SEASONS = ["2324", "2425", "2526"]

# Map football-data.co.uk league codes to DB league names
LEAGUE_FILES = {
    "E0": "Premier League",
    "SP1": "La Liga",
    "D1": "Bundesliga",
    "I1": "Serie A",
    "F1": "Ligue 1",
}

# Manual overrides for known name mismatches (CSV short name → DB team name substring).
# Used after the normalizer fails — only list teams where fuzzy match won't work.
NAME_OVERRIDES = {
    # Premier League
    "man united": "Manchester United",
    "man utd": "Manchester United",
    "man city": "Manchester City",
    "tottenham": "Tottenham Hotspur",
    "brighton": "Brighton & Hove Albion",
    "newcastle": "Newcastle United",
    "wolves": "Wolverhampton Wanderers",
    "bournemouth": "AFC Bournemouth",
    "nott'm forest": "Nottingham Forest",
    "leicester": "Leicester City",
    "west ham": "West Ham United",
    "leeds": "Leeds United",
    "sheffield united": "Sheffield United",
    "luton": "Luton Town",
    "burnley": "Burnley",
    "ipswich": "Ipswich Town",
    "southampton": "Southampton",
    "sunderland": "Sunderland",
    # La Liga
    "ath madrid": "Atlético Madrid",
    "ath bilbao": "Athletic Club",
    "athletic club": "Athletic Club",
    "betis": "Real Betis",
    "sociedad": "Real Sociedad",
    "celta": "Celta Vigo",
    "vallecano": "Rayo Vallecano",
    "alaves": "Alavés",
    "espanol": "Espanyol",
    "almeria": "Almería",
    "cadiz": "Cádiz",
    "granada": "Granada",
    "las palmas": "Las Palmas",
    "leganes": "Leganés",
    "real oviedo": "Real Oviedo",
    "valladolid": "Real Valladolid",
    # Bundesliga
    "bayern munich": "Bayern Munich",
    "dortmund": "Borussia Dortmund",
    "leverkusen": "Bayer Leverkusen",
    "ein frankfurt": "Eintracht Frankfurt",
    "m'gladbach": "Borussia Mönchengladbach",
    "monchengladbach": "Borussia Mönchengladbach",
    "stuttgart": "VfB Stuttgart",
    "wolfsburg": "VfL Wolfsburg",
    "hoffenheim": "1899 Hoffenheim",
    "union berlin": "Union Berlin",
    "werder bremen": "Werder Bremen",
    "heidenheim": "1. FC Heidenheim",
    "mainz": "Mainz 05",
    "augsburg": "FC Augsburg",
    "st pauli": "FC St. Pauli",
    "hamburg": "Hamburg SV",
    "koln": "FC Cologne",
    "fc koln": "FC Cologne",
    "darmstadt": "SV Darmstadt 98",
    "bochum": "VfL Bochum",
    # Serie A
    "inter": "Inter Milan",
    "ac milan": "AC Milan",
    "milan": "AC Milan",
    "juventus": "Juventus",
    "napoli": "Napoli",
    "roma": "AS Roma",
    "lazio": "Lazio",
    "fiorentina": "Fiorentina",
    "atalanta": "Atalanta",
    "torino": "Torino",
    "verona": "Hellas Verona",
    "genoa": "Genoa",
    "bologna": "Bologna",
    "udinese": "Udinese",
    "sassuolo": "Sassuolo",
    "cagliari": "Cagliari",
    "parma": "Parma",
    "como": "Como",
    "lecce": "Lecce",
    "pisa": "Pisa",
    "cremonese": "Cremonese",
    "empoli": "Empoli",
    "frosinone": "Frosinone",
    "salernitana": "Salernitana",
    "monza": "Monza",
    "venezia": "Venezia",
    # Ligue 1
    "paris sg": "Paris Saint-Germain",
    "psg": "Paris Saint-Germain",
    "marseille": "Olympique Marseille",
    "lyon": "Olympique Lyonnais",
    "monaco": "AS Monaco",
    "lille": "Lille",
    "nice": "OGC Nice",
    "rennes": "Stade Rennais",
    "strasbourg": "RC Strasbourg Alsace",
    "lens": "RC Lens",
    "nantes": "FC Nantes",
    "brest": "Stade Brestois 29",
    "toulouse": "Toulouse",
    "angers": "Angers SCO",
    "auxerre": "AJ Auxerre",
    "le havre": "Le Havre AC",
    "paris fc": "Paris FC",
    "metz": "FC Metz",
    "lorient": "FC Lorient",
    "reims": "Stade de Reims",
    "montpellier": "Montpellier HSC",
    "clermont": "Clermont Foot",
    "saint-etienne": "AS Saint-Étienne",
    "st etienne": "AS Saint-Étienne",
    "troyes": "ES Troyes",
    "ajaccio": "AC Ajaccio",
}


def normalize(name: str) -> str:
    """Strip punctuation, accents, common prefixes/suffixes, lowercase."""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.strip().lower()
    n = re.sub(r"[\.\,\'\-]", "", n)
    n = re.sub(r"\s+", " ", n)
    for suffix in (" fc", " cf", " afc", " sc"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    for prefix in ("fc ", "cf ", "afc ", "sc "):
        if n.startswith(prefix):
            n = n[len(prefix):]
    return n.strip()


def build_team_index(session, league_id: int) -> dict[str, Team]:
    """Build normalized-name → Team lookup for one league."""
    teams = session.query(Team).filter(Team.league_id == league_id).all()
    idx: dict[str, Team] = {}
    for t in teams:
        idx[normalize(t.name)] = t
    return idx


def find_team(csv_name: str, index: dict[str, Team], full_team_cache: list[Team]) -> Optional[Team]:
    """Resolve a CSV team name to a DB Team using normalizer + overrides + fuzzy fallback."""
    key = normalize(csv_name)

    # 1. Direct normalized match
    if key in index:
        return index[key]

    # 2. Manual override (try raw lower, then normalized key)
    override = NAME_OVERRIDES.get(csv_name.strip().lower()) or NAME_OVERRIDES.get(key)
    if override is not None:
        override_key = normalize(override)
        if override_key in index:
            return index[override_key]
        # Fallback: substring search against the override
        for team in full_team_cache:
            if override.lower() in team.name.lower() or team.name.lower() in override.lower():
                return team

    # 3. Substring fuzzy match (CSV short name contained in DB long name)
    candidates = [t for t in full_team_cache if key in normalize(t.name) or normalize(t.name) in key]
    if len(candidates) == 1:
        return candidates[0]

    # 4. First-word match
    first_word = key.split(" ")[0] if key else ""
    if len(first_word) >= 4:
        first_word_matches = [
            t for t in full_team_cache if normalize(t.name).startswith(first_word)
        ]
        if len(first_word_matches) == 1:
            return first_word_matches[0]

    return None


def resolve_or_create_team(
    session,
    csv_name: str,
    league: League,
    team_index: dict[str, Team],
    full_team_cache: list[Team],
    created_teams: set[str],
    apply: bool,
) -> Team:
    """Return a Team row, creating one if none matches (for relegated/promoted squads)."""
    found = find_team(csv_name, team_index, full_team_cache)
    if found is not None:
        return found

    # Resolve to a clean display name: prefer override, else title-case the CSV name
    override = NAME_OVERRIDES.get(csv_name.strip().lower()) or NAME_OVERRIDES.get(normalize(csv_name))
    display_name = override if override else csv_name.strip()

    new_team = Team(name=display_name, league_id=league.id)
    created_teams.add(f"{league.name}: {display_name}")
    if apply:
        session.add(new_team)
        session.flush()  # assign primary key
    else:
        # Give dry-run a stable identity so subsequent lookups in this run match
        new_team.id = -(len(created_teams))

    team_index[normalize(display_name)] = new_team
    full_team_cache.append(new_team)
    return new_team


def parse_csv_date(raw: str) -> Optional[datetime.date]:
    """Parse DD/MM/YY or DD/MM/YYYY."""
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_csv_time(raw: str) -> Optional[tuple[int, int]]:
    """Parse HH:MM into (hour, minute). Returns None if unparseable."""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            t = datetime.strptime(raw, fmt)
            return t.hour, t.minute
        except ValueError:
            continue
    return None


def build_kickoff(match_date, time_str: str) -> datetime:
    """Combine date + HH:MM into a datetime; default to 15:00 if time missing."""
    hm = parse_csv_time(time_str)
    hour, minute = hm if hm else (15, 0)
    return datetime.combine(match_date, datetime.min.time()).replace(hour=hour, minute=minute)


def parse_float(raw: str) -> Optional[float]:
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def parse_int(raw: str) -> Optional[int]:
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


def fetch_csv(season_code: str, league_code: str) -> list[dict]:
    url = f"https://www.football-data.co.uk/mmz4281/{season_code}/{league_code}.csv"
    print(f"  Fetching {url}...", end="", flush=True)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    # football-data.co.uk serves latin-1 with BOM; force-decode and strip BOM
    text = response.content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    print(f" {len(rows)} rows")
    return rows


def process_league_season(
    session,
    season_code: str,
    league_code: str,
    league_name: str,
    apply: bool,
) -> dict:
    stats = {
        "csv_rows": 0,
        "fixtures_created": 0,
        "fixtures_matched": 0,
        "results_created": 0,
        "results_updated": 0,
        "odds_created": 0,
        "odds_already": 0,
        "teams_created": set(),
        "skipped_bad_row": 0,
    }

    league = session.query(League).filter(League.name == league_name).first()
    if league is None:
        print(f"  SKIP: league '{league_name}' not in DB")
        return stats

    try:
        rows = fetch_csv(season_code, league_code)
    except Exception as exc:
        print(f"  ERROR fetching {season_code}/{league_code}: {exc}")
        return stats

    stats["csv_rows"] = len(rows)

    team_index = build_team_index(session, league.id)
    full_teams = list(team_index.values())

    for row in rows:
        csv_home = (row.get("HomeTeam") or "").strip()
        csv_away = (row.get("AwayTeam") or "").strip()
        if not csv_home or not csv_away:
            stats["skipped_bad_row"] += 1
            continue

        match_date = parse_csv_date(row.get("Date", ""))
        if match_date is None:
            stats["skipped_bad_row"] += 1
            continue

        home_team = resolve_or_create_team(
            session, csv_home, league, team_index, full_teams, stats["teams_created"], apply
        )
        away_team = resolve_or_create_team(
            session, csv_away, league, team_index, full_teams, stats["teams_created"], apply
        )

        kickoff_at = build_kickoff(match_date, row.get("Time", ""))

        # Find an existing fixture within ±1 day tolerance
        fixture = (
            session.query(Fixture)
            .filter(Fixture.league_id == league.id)
            .filter(Fixture.home_team_id == home_team.id)
            .filter(Fixture.away_team_id == away_team.id)
            .filter(Fixture.kickoff_at >= kickoff_at - timedelta(days=1))
            .filter(Fixture.kickoff_at <= kickoff_at + timedelta(days=2))
            .first()
        ) if home_team.id is not None and home_team.id > 0 and away_team.id and away_team.id > 0 else None

        if fixture is None:
            fixture = Fixture(
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                league_id=league.id,
                kickoff_at=kickoff_at,
                status="completed",
            )
            stats["fixtures_created"] += 1
            if apply:
                session.add(fixture)
                session.flush()
        else:
            stats["fixtures_matched"] += 1
            if apply and fixture.status != "completed":
                fixture.status = "completed"

        # Parse result
        home_score = parse_int(row.get("FTHG"))
        away_score = parse_int(row.get("FTAG"))
        ftr = (row.get("FTR") or "").strip().upper()
        outcome = {"H": "home", "D": "draw", "A": "away"}.get(ftr)
        ht_home = parse_int(row.get("HTHG"))
        ht_away = parse_int(row.get("HTAG"))
        htr = (row.get("HTR") or "").strip().upper()
        ht_outcome = {"H": "home", "D": "draw", "A": "away"}.get(htr)

        if home_score is not None and away_score is not None and outcome is not None:
            existing_result = (
                session.query(Result).filter(Result.fixture_id == fixture.id).first()
                if fixture.id and fixture.id > 0
                else None
            )
            if existing_result is None:
                res = Result(
                    fixture_id=fixture.id,
                    home_score=home_score,
                    away_score=away_score,
                    outcome=outcome,
                    ht_home_score=ht_home,
                    ht_away_score=ht_away,
                    ht_outcome=ht_outcome,
                    total_goals=home_score + away_score,
                    ht_total_goals=(ht_home + ht_away) if (ht_home is not None and ht_away is not None) else None,
                    verified_at=datetime.utcnow(),
                )
                stats["results_created"] += 1
                if apply:
                    session.add(res)
            elif existing_result.home_score is None or existing_result.away_score is None or existing_result.outcome is None:
                if apply:
                    existing_result.home_score = home_score
                    existing_result.away_score = away_score
                    existing_result.outcome = outcome
                    existing_result.ht_home_score = ht_home
                    existing_result.ht_away_score = ht_away
                    existing_result.ht_outcome = ht_outcome
                    existing_result.total_goals = home_score + away_score
                    existing_result.ht_total_goals = (
                        (ht_home + ht_away) if (ht_home is not None and ht_away is not None) else None
                    )
                    existing_result.verified_at = datetime.utcnow()
                stats["results_updated"] += 1

        # Odds
        home_odds = parse_float(row.get("B365H"))
        draw_odds = parse_float(row.get("B365D"))
        away_odds = parse_float(row.get("B365A"))
        over_odds = parse_float(row.get("B365>2.5"))
        under_odds = parse_float(row.get("B365<2.5"))

        if home_odds and away_odds:
            existing_snapshot = (
                session.query(OddsSnapshot)
                .filter(OddsSnapshot.fixture_id == fixture.id)
                .filter(OddsSnapshot.bookmaker == "bet365_historical")
                .first()
                if fixture.id and fixture.id > 0
                else None
            )
            if existing_snapshot is None:
                snap = OddsSnapshot(
                    fixture_id=fixture.id,
                    bookmaker="bet365_historical",
                    home_odds=home_odds,
                    draw_odds=draw_odds,
                    away_odds=away_odds,
                    total_goals_line=2.5 if (over_odds or under_odds) else None,
                    over_odds=over_odds,
                    under_odds=under_odds,
                    captured_at=kickoff_at - timedelta(hours=1),
                )
                stats["odds_created"] += 1
                if apply:
                    session.add(snap)
            else:
                stats["odds_already"] += 1

    if apply:
        session.commit()

    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually write rows (default: dry-run)")
    parser.add_argument(
        "--seasons",
        nargs="+",
        default=DEFAULT_SEASONS,
        help=f"Season codes to process (default: {DEFAULT_SEASONS})",
    )
    args = parser.parse_args()

    session = get_session()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== Football-Data.co.uk Multi-Season Backfill ({mode}) ===")
    print(f"Seasons: {args.seasons}\n")

    grand = {
        "csv_rows": 0,
        "fixtures_created": 0,
        "fixtures_matched": 0,
        "results_created": 0,
        "results_updated": 0,
        "odds_created": 0,
        "odds_already": 0,
        "skipped_bad_row": 0,
    }
    all_new_teams: set[str] = set()

    for season_code in args.seasons:
        print(f"\n### Season {season_code} ###")
        for league_code, league_name in LEAGUE_FILES.items():
            print(f"[{season_code}/{league_code}] {league_name}")
            stats = process_league_season(session, season_code, league_code, league_name, args.apply)
            for k in grand:
                grand[k] += stats[k]
            all_new_teams.update(stats["teams_created"])
            print(
                f"  rows={stats['csv_rows']}  fix(new/match)={stats['fixtures_created']}/{stats['fixtures_matched']}  "
                f"res(new/upd)={stats['results_created']}/{stats['results_updated']}  "
                f"odds(new/dup)={stats['odds_created']}/{stats['odds_already']}  "
                f"bad={stats['skipped_bad_row']}"
            )
            if stats["teams_created"]:
                print(f"  NEW TEAMS: {sorted(stats['teams_created'])}")

    print("\n=== Grand Totals ===")
    for k, v in grand.items():
        print(f"  {k}: {v}")
    if all_new_teams:
        print(f"\n  teams auto-created ({len(all_new_teams)}):")
        for t in sorted(all_new_teams):
            print(f"    - {t}")

    session.close()


if __name__ == "__main__":
    main()
