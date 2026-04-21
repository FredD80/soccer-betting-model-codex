from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.db.models import (
    Fixture,
    HistoricalOddsBundle,
    League,
    Result,
    Team,
    TeamAlias,
)
from app.team_matcher import resolve_team

SOURCE_NAME = "oddalerts"
DEFAULT_MARKETS = (6, 18, 19)
DEFAULT_BOOKMAKERS = (1, 2, 3, 4)


@dataclass
class OddAlertsBackfillStats:
    fixtures_seen: int = 0
    fixtures_with_odds: int = 0
    fixtures_created: int = 0
    fixtures_matched: int = 0
    teams_created: int = 0
    results_created: int = 0
    results_updated: int = 0
    bundles_created: int = 0
    bundles_updated: int = 0
    odds_rows_seen: int = 0
    skipped_rows: int = 0


class OddAlertsHistoricalOddsBackfill:
    def __init__(self, session, client):
        self.session = session
        self.client = client
        self._bundle_cache: dict[tuple[str, int, int, str], HistoricalOddsBundle] = {}
        self._team_cache: dict[tuple[int, str], Team] = {}
        self._created_bundle_keys: set[tuple[str, int, int, str]] = set()

    def run(
        self,
        *,
        competition_id: int,
        season_ids: Iterable[int],
        date_from: datetime,
        date_to: datetime,
        league_name: str | None = None,
        league_country: str | None = None,
        bookmakers: Iterable[int] = DEFAULT_BOOKMAKERS,
        markets: Iterable[int] = DEFAULT_MARKETS,
        chunk_size: int = 50,
    ) -> OddAlertsBackfillStats:
        fixtures = self.client.iter_fixtures_between(
            from_dt=date_from,
            to_dt=date_to,
            competitions=(competition_id,),
            seasons=season_ids,
        )
        stats = OddAlertsBackfillStats(fixtures_seen=len(fixtures))
        if not fixtures:
            return stats

        league = self._resolve_league(
            fixtures[0],
            league_name=league_name,
            league_country=league_country,
        )

        fixture_index: dict[int, dict[str, int]] = {}
        for raw_fixture in fixtures:
            local_fixture = self._upsert_fixture(league, raw_fixture, stats)
            fixture_index[int(raw_fixture["id"])] = {
                "fixture_id": int(local_fixture.id),
                "competition_id": int(raw_fixture["competition_id"]),
                "season_id": int(raw_fixture["season_id"]),
            }
            if raw_fixture.get("has_odds"):
                stats.fixtures_with_odds += 1

        source_fixture_ids = [
            int(raw_fixture["id"])
            for raw_fixture in fixtures
            if raw_fixture.get("has_odds")
        ]
        for offset in range(0, len(source_fixture_ids), chunk_size):
            payload = self.client.odds_history_multiple(
                source_fixture_ids[offset: offset + chunk_size],
                markets=markets,
                bookmakers=bookmakers,
            )
            for row in payload.get("data", []):
                stats.odds_rows_seen += 1
                if not self._apply_odds_row(row, fixture_index):
                    stats.skipped_rows += 1

        stats.bundles_created = len(self._created_bundle_keys)
        stats.bundles_updated = max(0, len(self._bundle_cache) - len(self._created_bundle_keys))

        return stats

    def _resolve_league(
        self,
        sample_fixture: dict,
        *,
        league_name: str | None,
        league_country: str | None,
    ) -> League:
        name = league_name or sample_fixture.get("competition_name")
        country = league_country or sample_fixture.get("competition_country")
        query = self.session.query(League).filter(League.name == name)
        if country:
            query = query.filter(League.country == country)
        league = query.first()
        if league is None:
            raise ValueError(f"League not found in local DB: {name!r} / {country!r}")
        return league

    def _resolve_or_create_team(self, league: League, raw_name: str, stats: OddAlertsBackfillStats) -> Team:
        key = (league.id, raw_name.strip().lower())
        cached = self._team_cache.get(key)
        if cached is not None:
            return cached

        team = resolve_team(self.session, league.id, raw_name, SOURCE_NAME)
        if team is None:
            team = Team(name=raw_name.strip(), league_id=league.id)
            self.session.add(team)
            self.session.flush()
            self.session.add(TeamAlias(team_id=team.id, alias=raw_name.strip(), source=SOURCE_NAME))
            stats.teams_created += 1

        self._team_cache[key] = team
        return team

    def _upsert_fixture(self, league: League, raw_fixture: dict, stats: OddAlertsBackfillStats) -> Fixture:
        home_team = self._resolve_or_create_team(league, raw_fixture["home_name"], stats)
        away_team = self._resolve_or_create_team(league, raw_fixture["away_name"], stats)
        kickoff_at = self._parse_utc(raw_fixture["date"])

        fixture = (
            self.session.query(Fixture)
            .filter(Fixture.league_id == league.id)
            .filter(Fixture.home_team_id == home_team.id)
            .filter(Fixture.away_team_id == away_team.id)
            .filter(Fixture.kickoff_at >= kickoff_at - timedelta(days=1))
            .filter(Fixture.kickoff_at <= kickoff_at + timedelta(days=1))
            .first()
        )

        if fixture is None:
            fixture = Fixture(
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                league_id=league.id,
                kickoff_at=kickoff_at,
                status=self._fixture_status(raw_fixture.get("status")),
            )
            self.session.add(fixture)
            self.session.flush()
            stats.fixtures_created += 1
        else:
            fixture.status = self._fixture_status(raw_fixture.get("status"))
            stats.fixtures_matched += 1

        self._upsert_result(fixture, raw_fixture, stats)
        return fixture

    def _upsert_result(self, fixture: Fixture, raw_fixture: dict, stats: OddAlertsBackfillStats) -> None:
        home_goals = raw_fixture.get("home_goals")
        away_goals = raw_fixture.get("away_goals")
        if home_goals is None or away_goals is None:
            return

        existing = self.session.query(Result).filter(Result.fixture_id == fixture.id).first()
        ht_home, ht_away = self._parse_halftime_score(raw_fixture.get("ht_score"))
        outcome = self._outcome(int(home_goals), int(away_goals))

        if existing is None:
            self.session.add(
                Result(
                    fixture_id=fixture.id,
                    home_score=int(home_goals),
                    away_score=int(away_goals),
                    outcome=outcome,
                    ht_home_score=ht_home,
                    ht_away_score=ht_away,
                    ht_outcome=self._outcome(ht_home, ht_away) if ht_home is not None and ht_away is not None else None,
                    total_goals=int(home_goals) + int(away_goals),
                    ht_total_goals=(ht_home + ht_away) if ht_home is not None and ht_away is not None else None,
                    verified_at=datetime.now(timezone.utc),
                )
            )
            stats.results_created += 1
            return

        existing.home_score = int(home_goals)
        existing.away_score = int(away_goals)
        existing.outcome = outcome
        existing.ht_home_score = ht_home
        existing.ht_away_score = ht_away
        existing.ht_outcome = self._outcome(ht_home, ht_away) if ht_home is not None and ht_away is not None else None
        existing.total_goals = int(home_goals) + int(away_goals)
        existing.ht_total_goals = (ht_home + ht_away) if ht_home is not None and ht_away is not None else None
        existing.verified_at = datetime.now(timezone.utc)
        stats.results_updated += 1

    def _apply_odds_row(self, row: dict, fixture_index: dict[int, dict[str, int]]) -> bool:
        source_fixture_id = int(row["fixture_id"])
        fixture_meta = fixture_index.get(source_fixture_id)
        if fixture_meta is None:
            return False

        wrote_any = False
        for odds_type in ("opening", "closing", "peak"):
            price = self._parse_float(row.get(odds_type))
            if price is None:
                continue
            bundle = self._get_or_create_bundle(
                fixture_id=fixture_meta["fixture_id"],
                source_fixture_id=source_fixture_id,
                competition_id=fixture_meta["competition_id"],
                season_id=fixture_meta["season_id"],
                bookmaker_id=int(row["bookmaker_id"]),
                bookmaker_name=str(row["bookmaker_name"]),
                odds_type=odds_type,
            )
            if self._assign_price(bundle, row["market_key"], row["outcome"], price):
                wrote_any = True
        return wrote_any

    def _get_or_create_bundle(
        self,
        *,
        fixture_id: int,
        source_fixture_id: int,
        competition_id: int,
        season_id: int,
        bookmaker_id: int,
        bookmaker_name: str,
        odds_type: str,
    ) -> HistoricalOddsBundle:
        cache_key = (SOURCE_NAME, source_fixture_id, bookmaker_id, odds_type)
        cached = self._bundle_cache.get(cache_key)
        if cached is not None:
            return cached

        bundle = (
            self.session.query(HistoricalOddsBundle)
            .filter(HistoricalOddsBundle.source == SOURCE_NAME)
            .filter(HistoricalOddsBundle.source_fixture_id == source_fixture_id)
            .filter(HistoricalOddsBundle.bookmaker_id == bookmaker_id)
            .filter(HistoricalOddsBundle.odds_type == odds_type)
            .first()
        )
        if bundle is None:
            bundle = HistoricalOddsBundle(
                fixture_id=fixture_id,
                source=SOURCE_NAME,
                source_fixture_id=source_fixture_id,
                competition_id=competition_id,
                season_id=season_id,
                bookmaker_id=bookmaker_id,
                bookmaker_name=bookmaker_name,
                odds_type=odds_type,
            )
            self.session.add(bundle)
            self.session.flush()
            self._created_bundle_keys.add(cache_key)
        else:
            bundle.fixture_id = fixture_id
            bundle.competition_id = competition_id
            bundle.season_id = season_id
            bundle.bookmaker_name = bookmaker_name
            bundle.imported_at = datetime.now(timezone.utc)

        self._bundle_cache[cache_key] = bundle
        return bundle

    def _assign_price(self, bundle: HistoricalOddsBundle, market_key: str, outcome: str, price: float) -> bool:
        if market_key == "ft_result":
            if outcome == "home":
                bundle.home_odds = price
                return True
            if outcome == "draw":
                bundle.draw_odds = price
                return True
            if outcome == "away":
                bundle.away_odds = price
                return True
            return False

        if market_key == "home_goals":
            if outcome in {"over_15", "over_1.5"}:
                bundle.home_team_total_1_5_over_odds = price
                return True
            if outcome in {"under_15", "under_1.5"}:
                bundle.home_team_total_1_5_under_odds = price
                return True
            return False

        if market_key == "away_goals":
            if outcome in {"over_15", "over_1.5"}:
                bundle.away_team_total_1_5_over_odds = price
                return True
            if outcome in {"under_15", "under_1.5"}:
                bundle.away_team_total_1_5_under_odds = price
                return True
            return False

        return False

    def _parse_halftime_score(self, score: str | None) -> tuple[int | None, int | None]:
        if not score or "-" not in score:
            return None, None
        try:
            home_raw, away_raw = score.split("-", 1)
            return int(home_raw), int(away_raw)
        except ValueError:
            return None, None

    def _fixture_status(self, raw_status: str | None) -> str:
        if raw_status in {"FT", "AET", "PEN", "WO", "AWD"}:
            return "completed"
        if raw_status in {"NS", "TBD", "POSTP"}:
            return "scheduled"
        return "live"

    def _outcome(self, home_score: int, away_score: int) -> str:
        if home_score > away_score:
            return "home"
        if away_score > home_score:
            return "away"
        return "draw"

    def _parse_utc(self, value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)

    def _parse_float(self, value: object) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
