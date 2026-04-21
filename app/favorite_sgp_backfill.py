from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import aliased

from app.db.models import (
    FavoriteSgpBacktestRow,
    Fixture,
    HistoricalOddsBundle,
    League,
    Result,
    Team,
)

DEFAULT_SYNTH_FACTOR = 0.75


@dataclass
class FavoriteSgpBacktestStats:
    bundles_seen: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    rows_deleted: int = 0
    rows_skipped: int = 0


class FavoriteSgpBacktestBuilder:
    def __init__(self, session, *, synth_factor: float = DEFAULT_SYNTH_FACTOR):
        self.session = session
        self.synth_factor = synth_factor

    def run(
        self,
        *,
        league_name: str | None = None,
        league_country: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> FavoriteSgpBacktestStats:
        home_team = aliased(Team)
        away_team = aliased(Team)
        query = (
            self.session.query(HistoricalOddsBundle, Fixture, League, Result, home_team, away_team)
            .join(Fixture, HistoricalOddsBundle.fixture_id == Fixture.id)
            .join(League, Fixture.league_id == League.id)
            .join(home_team, Fixture.home_team_id == home_team.id)
            .join(away_team, Fixture.away_team_id == away_team.id)
            .outerjoin(Result, Result.fixture_id == Fixture.id)
        )
        if league_name:
            query = query.filter(League.name == league_name)
        if league_country:
            query = query.filter(League.country == league_country)
        if date_from is not None:
            query = query.filter(Fixture.kickoff_at >= date_from)
        if date_to is not None:
            query = query.filter(Fixture.kickoff_at <= date_to)

        bundles = query.all()
        stats = FavoriteSgpBacktestStats(bundles_seen=len(bundles))
        if not bundles:
            return stats

        existing_rows = {
            row.historical_bundle_id: row
            for row in (
                self.session.query(FavoriteSgpBacktestRow)
                .filter(
                    FavoriteSgpBacktestRow.historical_bundle_id.in_(
                        [bundle.id for bundle, *_ in bundles]
                    )
                )
                .all()
            )
        }

        for bundle, fixture, league, result, home, away in bundles:
            payload = self._build_payload(bundle, fixture, league, result, home, away)
            existing = existing_rows.get(bundle.id)
            if payload is None:
                if existing is not None:
                    self.session.delete(existing)
                    stats.rows_deleted += 1
                else:
                    stats.rows_skipped += 1
                continue

            if existing is None:
                self.session.add(FavoriteSgpBacktestRow(**payload))
                stats.rows_created += 1
                continue

            for key, value in payload.items():
                setattr(existing, key, value)
            stats.rows_updated += 1

        return stats

    def _build_payload(
        self,
        bundle: HistoricalOddsBundle,
        fixture: Fixture,
        league: League,
        result: Result | None,
        home_team: Team,
        away_team: Team,
    ) -> dict | None:
        favorite_side = self._favorite_side(bundle.home_odds, bundle.away_odds)
        if favorite_side is None:
            return None

        if favorite_side == "home":
            favorite_team = home_team
            underdog_team = away_team
            favorite_ml_odds = bundle.home_odds
            underdog_ml_odds = bundle.away_odds
            favorite_over_odds = bundle.home_team_total_1_5_over_odds
            favorite_under_odds = bundle.home_team_total_1_5_under_odds
            actual_combo_odds = bundle.home_win_and_home_over_1_5_odds
            favorite_goals = result.home_score if result and result.home_score is not None else None
            favorite_won = (result.outcome == "home") if result and result.outcome is not None else None
        else:
            favorite_team = away_team
            underdog_team = home_team
            favorite_ml_odds = bundle.away_odds
            underdog_ml_odds = bundle.home_odds
            favorite_over_odds = bundle.away_team_total_1_5_over_odds
            favorite_under_odds = bundle.away_team_total_1_5_under_odds
            actual_combo_odds = bundle.away_win_and_away_over_1_5_odds
            favorite_goals = result.away_score if result and result.away_score is not None else None
            favorite_won = (result.outcome == "away") if result and result.outcome is not None else None

        p_favorite_win_fair = self._devig_two_way_first(favorite_ml_odds, underdog_ml_odds)
        p_favorite_over_fair = self._devig_two_way_first(favorite_over_odds, favorite_under_odds)
        p_joint_fair_independent = None
        if p_favorite_win_fair is not None and p_favorite_over_fair is not None:
            p_joint_fair_independent = p_favorite_win_fair * p_favorite_over_fair

        sgp_synth_odds = self._synthesized_sgp_odds(
            favorite_ml_odds=favorite_ml_odds,
            underdog_ml_odds=underdog_ml_odds,
            favorite_over_odds=favorite_over_odds,
            favorite_under_odds=favorite_under_odds,
        )
        sgp_usable_odds = actual_combo_odds or sgp_synth_odds
        if sgp_usable_odds is None:
            return None

        favorite_scored_2_plus = None if favorite_goals is None else favorite_goals >= 2
        favorite_ml_and_over_hit = None
        if favorite_won is not None and favorite_scored_2_plus is not None:
            favorite_ml_and_over_hit = favorite_won and favorite_scored_2_plus

        built_at = datetime.now(timezone.utc)
        return {
            "historical_bundle_id": bundle.id,
            "fixture_id": fixture.id,
            "league_id": league.id,
            "kickoff_at": fixture.kickoff_at,
            "bookmaker_id": bundle.bookmaker_id,
            "bookmaker_name": bundle.bookmaker_name,
            "odds_type": bundle.odds_type,
            "favorite_side": favorite_side,
            "favorite_team_id": favorite_team.id,
            "favorite_team_name": favorite_team.name,
            "underdog_team_id": underdog_team.id,
            "underdog_team_name": underdog_team.name,
            "favorite_ml_odds": favorite_ml_odds,
            "favorite_ml_american_odds": self._decimal_to_american(favorite_ml_odds),
            "underdog_ml_odds": underdog_ml_odds,
            "underdog_ml_american_odds": self._decimal_to_american(underdog_ml_odds),
            "draw_odds": bundle.draw_odds,
            "draw_american_odds": self._decimal_to_american(bundle.draw_odds),
            "favorite_team_total_over_1_5_odds": favorite_over_odds,
            "favorite_team_total_over_1_5_american_odds": self._decimal_to_american(favorite_over_odds),
            "favorite_team_total_under_1_5_odds": favorite_under_odds,
            "favorite_team_total_under_1_5_american_odds": self._decimal_to_american(favorite_under_odds),
            "p_favorite_win_fair": p_favorite_win_fair,
            "p_favorite_team_total_over_1_5_fair": p_favorite_over_fair,
            "p_joint_fair_independent": p_joint_fair_independent,
            "sgp_actual_odds": actual_combo_odds,
            "sgp_actual_american_odds": self._decimal_to_american(actual_combo_odds),
            "sgp_synth_odds": sgp_synth_odds,
            "sgp_synth_american_odds": self._decimal_to_american(sgp_synth_odds),
            "sgp_usable_odds": sgp_usable_odds,
            "sgp_usable_american_odds": self._decimal_to_american(sgp_usable_odds),
            "favorite_won": favorite_won,
            "favorite_scored_2_plus": favorite_scored_2_plus,
            "favorite_ml_and_over_1_5_hit": favorite_ml_and_over_hit,
            "built_at": built_at,
        }

    def _favorite_side(
        self,
        home_odds: float | None,
        away_odds: float | None,
    ) -> str | None:
        if home_odds is None or away_odds is None or home_odds == away_odds:
            return None
        return "home" if home_odds < away_odds else "away"

    def _synthesized_sgp_odds(
        self,
        *,
        favorite_ml_odds: float | None,
        underdog_ml_odds: float | None,
        favorite_over_odds: float | None,
        favorite_under_odds: float | None,
    ) -> float | None:
        p_favorite_win_fair = self._devig_two_way_first(favorite_ml_odds, underdog_ml_odds)
        p_favorite_over_fair = self._devig_two_way_first(favorite_over_odds, favorite_under_odds)
        if p_favorite_win_fair is None or p_favorite_over_fair is None:
            return None
        market_prob = min(0.99, max(0.0, (p_favorite_win_fair * p_favorite_over_fair) / self.synth_factor))
        if market_prob <= 0.0:
            return None
        return 1.0 / market_prob

    def _devig_two_way_first(self, odds_a: float | None, odds_b: float | None) -> float | None:
        if odds_a is None or odds_b is None or odds_a <= 1.0 or odds_b <= 1.0:
            return None
        imp_a = 1.0 / odds_a
        imp_b = 1.0 / odds_b
        overround = imp_a + imp_b
        if overround <= 0.0:
            return None
        return imp_a / overround

    def _decimal_to_american(self, decimal_odds: float | None) -> int | None:
        if decimal_odds is None or decimal_odds <= 1.0:
            return None
        if decimal_odds >= 2.0:
            return int(round((decimal_odds - 1.0) * 100))
        return int(round(-100 / (decimal_odds - 1.0)))
