from datetime import datetime, timedelta, timezone

import click
from app.db.connection import get_session
from app.db.models import Base
from app.db.connection import engine
from app.logging_config import configure_logging

configure_logging()

PARALLEL_SPREAD_WEIGHTS = (0.75, 0.25)
PARALLEL_OU_WEIGHTS = (0.70, 0.30)
PARALLEL_MONEYLINE_WEIGHTS = (0.20, 0.80)
PARALLEL_NO_MARKET_PRIOR_BASE = 0.30
PARALLEL_NO_MARKET_PRIOR_EXTRA = 0.20

# Import all user-defined model classes here as they are added
MODEL_CLASSES = []  # e.g. [MyModelV1, MyModelV2]


@click.group()
def cli():
    """Soccer Betting Model CLI"""


def _parse_utc_date_start(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _parse_utc_date_end(value: str) -> datetime:
    return _parse_utc_date_start(value) + timedelta(days=1) - timedelta(microseconds=1)


@cli.command()
def migrate():
    """Run database migrations (creates tables)."""
    Base.metadata.create_all(engine)
    click.echo("Database tables created.")


@cli.command()
def seed():
    """Seed the database with the supported leagues."""
    from app.db.models import League
    session = get_session()
    leagues = [
        {"name": "Premier League",   "country": "England", "espn_id": "eng.1",          "odds_api_key": "soccer_epl"},
        {"name": "La Liga",          "country": "Spain",   "espn_id": "esp.1",          "odds_api_key": "soccer_spain_la_liga"},
        {"name": "Bundesliga",       "country": "Germany", "espn_id": "ger.1",          "odds_api_key": "soccer_germany_bundesliga"},
        {"name": "Serie A",          "country": "Italy",   "espn_id": "ita.1",          "odds_api_key": "soccer_italy_serie_a"},
        {"name": "Ligue 1",          "country": "France",  "espn_id": "fra.1",          "odds_api_key": "soccer_france_ligue_one"},
        {"name": "Primeira Liga",    "country": "Portugal","espn_id": "por.1",          "odds_api_key": "soccer_portugal_primeira_liga"},
        {"name": "MLS",              "country": "USA",     "espn_id": "usa.1",          "odds_api_key": "soccer_usa_mls"},
        {"name": "Champions League", "country": "Europe",  "espn_id": "uefa.champions", "odds_api_key": "soccer_uefa_champs_league"},
    ]
    try:
        added = 0
        for data in leagues:
            existing = session.query(League).filter_by(espn_id=data["espn_id"]).first()
            if not existing:
                session.add(League(**data))
                added += 1
        session.commit()
        click.echo(f"Seeded {added} league(s). {len(leagues) - added} already existed.")
    finally:
        session.close()


@cli.command()
def collect():
    """Run data collection now (fixtures + odds)."""
    from app.collector.collector import DataCollector
    session = get_session()
    try:
        DataCollector(session).run()
        click.echo("Data collection complete.")
    finally:
        session.close()


@cli.command()
def build_form_cache():
    """Build/refresh form cache for all teams from completed results."""
    from app.form_cache import FormCacheBuilder
    session = get_session()
    try:
        count = FormCacheBuilder(session).build_all()
        click.echo(f"Form cache updated: {count} team/home entries written.")
    finally:
        session.close()


@cli.command()
def predict_spreads():
    """Run spread predictor for upcoming fixtures."""
    from app.spread_predictor import SpreadPredictor
    from app.db.models import ModelVersion
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="spread_v1", active=True).first()
        if not mv:
            from app.config import settings
            mv = ModelVersion(name="spread_v1", version=settings.spread_model_version,
                              description="Phase 1 Poisson spread predictor", active=True)
            session.add(mv)
            session.flush()
        from app.config import settings as _s
        SpreadPredictor(session, ml_enabled=_s.ml_lambda_enabled).run(mv.id)
        session.commit()
        click.echo("Spread predictions complete.")
    finally:
        session.close()


@cli.command()
def predict_ou():
    """Run O/U analyzer for upcoming fixtures."""
    from app.ou_analyzer import OUAnalyzer
    from app.db.models import ModelVersion
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="ou_v1", active=True).first()
        if not mv:
            from app.config import settings
            mv = ModelVersion(name="ou_v1", version=settings.ou_model_version,
                              description="Phase 1 Poisson O/U analyzer", active=True)
            session.add(mv)
            session.flush()
        from app.config import settings as _s
        OUAnalyzer(session, ml_enabled=_s.ml_lambda_enabled).run(mv.id)
        session.commit()
        click.echo("O/U analysis complete.")
    finally:
        session.close()


@cli.command()
def predict_moneyline():
    """Run 3-way moneyline predictor for upcoming fixtures."""
    from app.moneyline_predictor import MoneylinePredictor
    from app.db.models import ModelVersion
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="moneyline_v1", active=True).first()
        if not mv:
            mv = ModelVersion(name="moneyline_v1", version="1.0.0",
                              description="Dixon-Coles 3-way moneyline", active=True)
            session.add(mv)
            session.flush()
        from app.config import settings as _s
        MoneylinePredictor(session, ml_enabled=_s.ml_lambda_enabled).run(mv.id)
        session.commit()
        click.echo("Moneyline predictions complete.")
    finally:
        session.close()


@cli.command()
def predict_parallel_spreads():
    """Run parallel spread predictor for upcoming fixtures."""
    from app.spread_predictor import SpreadPredictor
    from app.db.models import ModelVersion
    from app.config import settings as _s
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="parallel_spread_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="parallel_spread_v1",
                version=_s.spread_model_version,
                description="Parallel spread predictor with stronger market and prior shrink",
                active=True,
            )
            session.add(mv)
            session.flush()
        SpreadPredictor(
            session,
            ml_enabled=_s.ml_lambda_enabled,
            market_weights_override=PARALLEL_SPREAD_WEIGHTS,
            no_market_prior_base=PARALLEL_NO_MARKET_PRIOR_BASE,
            no_market_prior_extra=PARALLEL_NO_MARKET_PRIOR_EXTRA,
        ).run(mv.id)
        session.commit()
        click.echo("Parallel spread predictions complete.")
    finally:
        session.close()


@cli.command()
def predict_parallel_ou():
    """Run parallel O/U analyzer for upcoming fixtures."""
    from app.ou_analyzer import OUAnalyzer
    from app.db.models import ModelVersion
    from app.config import settings as _s
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="parallel_ou_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="parallel_ou_v1",
                version=_s.ou_model_version,
                description="Parallel O/U analyzer with stronger market and prior shrink",
                active=True,
            )
            session.add(mv)
            session.flush()
        OUAnalyzer(
            session,
            ml_enabled=_s.ml_lambda_enabled,
            market_weights_override=PARALLEL_OU_WEIGHTS,
            no_market_prior_base=PARALLEL_NO_MARKET_PRIOR_BASE,
            no_market_prior_extra=PARALLEL_NO_MARKET_PRIOR_EXTRA,
        ).run(mv.id)
        session.commit()
        click.echo("Parallel O/U analysis complete.")
    finally:
        session.close()


@cli.command()
def predict_parallel_moneyline():
    """Run parallel 3-way moneyline predictor for upcoming fixtures."""
    from app.moneyline_predictor import MoneylinePredictor
    from app.db.models import ModelVersion
    from app.config import settings as _s
    session = get_session()
    try:
        mv = session.query(ModelVersion).filter_by(name="parallel_moneyline_v1", active=True).first()
        if not mv:
            mv = ModelVersion(
                name="parallel_moneyline_v1",
                version="1.0.0",
                description="Parallel moneyline predictor with stronger market and prior shrink",
                active=True,
            )
            session.add(mv)
            session.flush()
        MoneylinePredictor(
            session,
            ml_enabled=_s.ml_lambda_enabled,
            market_weights_override=PARALLEL_MONEYLINE_WEIGHTS,
            no_market_prior_base=PARALLEL_NO_MARKET_PRIOR_BASE,
            no_market_prior_extra=PARALLEL_NO_MARKET_PRIOR_EXTRA,
        ).run(mv.id)
        session.commit()
        click.echo("Parallel moneyline predictions complete.")
    finally:
        session.close()


@cli.command()
def predict():
    """Run prediction engine now for upcoming fixtures."""
    from app.predictor import PredictionEngine
    session = get_session()
    try:
        PredictionEngine(session, model_classes=MODEL_CLASSES).run()
        click.echo("Predictions complete.")
    finally:
        session.close()


@cli.command()
@click.option("--model", required=True, help="Model name")
@click.option("--version", required=True, help="Model version")
@click.option("--from-date", required=True, help="Start date YYYY-MM-DD")
@click.option("--to-date", required=True, help="End date YYYY-MM-DD")
def backtest(model, version, from_date, to_date):
    """Backtest a model version against historical data."""
    from app.backtester import Backtester
    from datetime import datetime
    session = get_session()
    try:
        date_from = datetime.strptime(from_date, "%Y-%m-%d")
        date_to = datetime.strptime(to_date, "%Y-%m-%d")
        Backtester(session, model_classes=MODEL_CLASSES).run(model, version, date_from, date_to)
        click.echo(f"Backtest complete for {model}@{version}.")
    finally:
        session.close()


@cli.command()
@click.option("--from-date", required=True, help="Start date YYYY-MM-DD")
@click.option("--to-date", required=True, help="End date YYYY-MM-DD")
@click.option(
    "--market",
    "markets",
    multiple=True,
    type=click.Choice(["spread", "ou", "moneyline"]),
    help="Limit to one or more markets; defaults to all supported markets.",
)
def backtest_picks(from_date, to_date, markets):
    """Backtest stored spread/OU/moneyline picks over completed fixtures."""
    from app.pick_backtester import PickBacktester
    from datetime import datetime

    session = get_session()
    try:
        date_from = datetime.strptime(from_date, "%Y-%m-%d")
        date_to = datetime.strptime(to_date, "%Y-%m-%d")
        selected = tuple(markets) if markets else ("spread", "ou", "moneyline")
        summaries = PickBacktester(session).run(date_from, date_to, markets=selected)
        if not summaries:
            click.echo("No qualifying stored picks found for the requested window.")
            return
        click.echo(f"\n{'Market':<12} {'Model ID':<10} {'Total':>6} {'Correct':>8} {'Accuracy':>10} {'ROI':>8}")
        click.echo("-" * 62)
        for summary in summaries:
            click.echo(
                f"{summary.market:<12} {summary.model_id:<10} {summary.total:>6} "
                f"{summary.correct:>8} {summary.accuracy:>10.1%} {summary.roi:>8.3f}"
            )
    finally:
        session.close()


@cli.command()
@click.argument("name")
@click.argument("version")
@click.option("--description", default="", help="Model description")
@click.option("--activate", is_flag=True, default=False, help="Activate immediately")
def register_model(name, version, description, activate):
    """Register a new model version."""
    from app.models.registry import ModelRegistry
    session = get_session()
    try:
        registry = ModelRegistry(session)
        registry.register(name, version, description)
        if activate:
            registry.activate(name, version)
            click.echo(f"Registered and activated {name}@{version}.")
        else:
            click.echo(f"Registered {name}@{version} (inactive). Run activate-model to enable.")
    finally:
        session.close()


@cli.command()
@click.argument("name")
@click.argument("version")
def activate_model(name, version):
    """Activate a registered model version."""
    from app.models.registry import ModelRegistry
    session = get_session()
    try:
        ModelRegistry(session).activate(name, version)
        click.echo(f"Activated {name}@{version}.")
    finally:
        session.close()


@cli.command()
def performance():
    """Print accuracy and ROI per model version and bet type."""
    from app.db.models import Performance, ModelVersion
    session = get_session()
    try:
        rows = session.query(Performance).all()
        if not rows:
            click.echo("No performance data yet.")
            return
        click.echo(f"\n{'Model':<20} {'Version':<10} {'Bet Type':<15} {'Preds':>6} {'Correct':>8} {'Accuracy':>10} {'ROI':>8}")
        click.echo("-" * 80)
        for p in rows:
            mv = session.query(ModelVersion).filter_by(id=p.model_id).first()
            click.echo(f"{mv.name:<20} {mv.version:<10} {p.bet_type:<15} {p.total_predictions:>6} "
                       f"{p.correct:>8} {p.accuracy:>10.1%} {p.roi:>8.3f}")
    finally:
        session.close()


@cli.command()
@click.option("--fixture-id", required=True, type=int, help="Fixture id")
@click.option("--market-type", required=True, type=click.Choice(["moneyline", "spread", "ou"]))
@click.option("--selection", required=True, help="home|draw|away for moneyline, home|away for spread, over|under for ou")
@click.option("--line", type=float, default=None, help="Required for spread and ou")
@click.option("--decimal-odds", type=float, default=None, help="Decimal odds")
@click.option("--american-odds", type=int, default=None, help="American odds")
@click.option("--stake-units", type=float, default=1.0, show_default=True, help="Stake size in units")
@click.option("--bookmaker", default="", help="Optional bookmaker label")
@click.option("--notes", default="", help="Optional note")
def add_manual_pick(fixture_id, market_type, selection, line, decimal_odds, american_odds, stake_units, bookmaker, notes):
    """Record a manual pick to be settled automatically when results arrive."""
    from datetime import datetime, timezone
    from app.db.models import Fixture, ManualPick
    from app.tracker import decimal_to_american

    def american_to_decimal(odds: int) -> float:
        if odds > 0:
            return 1.0 + (odds / 100.0)
        return 1.0 + (100.0 / abs(odds))

    valid_selection = {
        "moneyline": {"home", "draw", "away"},
        "spread": {"home", "away"},
        "ou": {"over", "under"},
    }

    session = get_session()
    try:
        fixture = session.query(Fixture).filter_by(id=fixture_id).first()
        if fixture is None:
            raise click.ClickException(f"Fixture {fixture_id} not found.")
        if selection not in valid_selection[market_type]:
            raise click.ClickException(f"Invalid selection '{selection}' for market type '{market_type}'.")
        if market_type in ("spread", "ou") and line is None:
            raise click.ClickException("--line is required for spread and ou picks.")
        if decimal_odds is None and american_odds is None:
            raise click.ClickException("Provide --decimal-odds or --american-odds.")

        final_decimal = decimal_odds if decimal_odds is not None else american_to_decimal(american_odds)
        final_american = american_odds if american_odds is not None else decimal_to_american(final_decimal)

        pick = ManualPick(
            fixture_id=fixture_id,
            market_type=market_type,
            selection=selection,
            line=line,
            decimal_odds=final_decimal,
            american_odds=final_american,
            stake_units=stake_units,
            bookmaker=bookmaker or None,
            notes=notes or None,
            result_status="open",
            created_at=datetime.now(timezone.utc),
        )
        session.add(pick)
        session.commit()
        click.echo(f"Saved manual pick {pick.id} for fixture {fixture_id}.")
    finally:
        session.close()


@cli.command()
def settle_predictions():
    """Settle live moneyline/spread/OU picks for fixtures with recorded results."""
    from app.tracker import ResultsTracker
    from app.db.models import Result

    session = get_session()
    try:
        tracker = ResultsTracker(session)
        fixture_ids = [row.fixture_id for row in session.query(Result.fixture_id).all()]
        settled = 0
        manual_settled = 0
        for fixture_id in fixture_ids:
            settled += tracker.settle_live_predictions(fixture_id)
            manual_settled += tracker.settle_manual_picks(fixture_id)
        click.echo(f"Settled {settled} live prediction row(s) and {manual_settled} manual pick(s).")
    finally:
        session.close()


@cli.command()
def compare_manual_picks():
    """Print summary comparison of manual picks versus matched model picks."""
    from app.db.models import ManualPick, PredictionOutcome, ModelVersion, Fixture, League

    session = get_session()
    try:
        manual_rows = (
            session.query(ManualPick)
            .filter(ManualPick.result_status.in_(("win", "loss", "push")))
            .all()
        )
        summary: dict[tuple[str, str, str, str], dict] = {}

        for manual in manual_rows:
            fixture = session.query(Fixture).filter_by(id=manual.fixture_id).first()
            league = session.query(League).filter_by(id=fixture.league_id).first() if fixture else None
            model_rows = (
                session.query(PredictionOutcome)
                .filter(PredictionOutcome.fixture_id == manual.fixture_id)
                .filter(PredictionOutcome.market_type == manual.market_type)
                .filter(PredictionOutcome.selection == manual.selection)
                .filter(PredictionOutcome.result_status.in_(("win", "loss", "push")))
                .all()
            )
            for model_row in model_rows:
                same_line = (
                    (manual.line is None and model_row.line is None)
                    or (manual.line is not None and model_row.line is not None and abs(manual.line - model_row.line) < 1e-6)
                )
                if not same_line:
                    continue
                mv = session.query(ModelVersion).filter_by(id=model_row.model_id).first()
                key = (
                    mv.name if mv else "unknown",
                    mv.version if mv else "unknown",
                    manual.market_type,
                    league.name if league else "Unknown",
                )
                bucket = summary.setdefault(key, {
                    "compared": 0,
                    "manual_profit": 0.0,
                    "model_profit": 0.0,
                    "manual_stake": 0.0,
                })
                bucket["compared"] += 1
                bucket["manual_profit"] += manual.profit_units or 0.0
                bucket["model_profit"] += model_row.profit_units or 0.0
                bucket["manual_stake"] += manual.stake_units or 0.0

        if not summary:
            click.echo("No matched manual-vs-model comparisons yet.")
            return

        click.echo(f"\n{'Model':<20} {'Version':<10} {'Market':<12} {'League':<20} {'Cmp':>5} {'My ROI':>8} {'Model ROI':>10}")
        click.echo("-" * 95)
        for (name, version, market, league), bucket in sorted(summary.items()):
            compared = bucket["compared"]
            my_roi = (bucket["manual_profit"] / bucket["manual_stake"]) if bucket["manual_stake"] else 0.0
            model_roi = (bucket["model_profit"] / compared) if compared else 0.0
            click.echo(f"{name:<20} {version:<10} {market:<12} {league:<20} {compared:>5} {my_roi:>8.3f} {model_roi:>10.3f}")
    finally:
        session.close()


@cli.command()
@click.option("--from-date", required=True, help="Start date YYYY-MM-DD")
@click.option("--to-date", default=None, help="End date YYYY-MM-DD")
@click.option("--limit", type=int, default=None, help="Stop after collecting this many bully spots")
@click.option("--max-checked", type=int, default=None, help="Stop after checking this many completed fixtures")
def analyze_bully_sgp(from_date: str, to_date: str | None, limit: int | None, max_checked: int | None):
    """Replay completed Bully spots and print SGP Lens band/threshold hit rates."""
    from app.sgp_analysis import (
        replay_bully_sgp_rows,
        summarize_sgp_bands,
        summarize_sgp_thresholds,
    )

    date_from = _parse_utc_date_start(from_date)
    date_to = (
        _parse_utc_date_end(to_date)
        if to_date
        else datetime.now(timezone.utc)
    )

    session = get_session()
    try:
        rows = replay_bully_sgp_rows(
            session,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            max_checked=max_checked,
            enable_understat_fetch=False,
        )
        if not rows:
            click.echo("No completed bully spots found in the requested window.")
            return

        overall_win_rate = sum(1.0 if row.favorite_win else 0.0 for row in rows) / len(rows)
        overall_sgp_rate = sum(1.0 if row.sgp_hit else 0.0 for row in rows) / len(rows)
        click.echo(
            f"Replayed {len(rows)} bully spots from {date_from.date()} to {date_to.date()} "
            f"(win {overall_win_rate:.1%}, SGP {overall_sgp_rate:.1%})."
        )

        click.echo("\nBands")
        click.echo(f"{'Range':<14} {'Total':>6} {'Win':>8} {'SGP':>8}")
        click.echo("-" * 40)
        for summary in summarize_sgp_bands(rows):
            win_text = "—" if summary.win_rate is None else f"{summary.win_rate:.1%}"
            sgp_text = "—" if summary.sgp_hit_rate is None else f"{summary.sgp_hit_rate:.1%}"
            click.echo(f"{summary.low:>4.2f}-{summary.high:<7.2f} {summary.total:>6} {win_text:>8} {sgp_text:>8}")

        click.echo("\nThresholds")
        click.echo(f"{'SGP >=':<14} {'Total':>6} {'Win':>8} {'SGP':>8}")
        click.echo("-" * 40)
        for summary in summarize_sgp_thresholds(rows):
            win_text = "—" if summary.win_rate is None else f"{summary.win_rate:.1%}"
            sgp_text = "—" if summary.sgp_hit_rate is None else f"{summary.sgp_hit_rate:.1%}"
            click.echo(f"{summary.threshold:>4.2f}{'':<8} {summary.total:>6} {win_text:>8} {sgp_text:>8}")
    finally:
        session.close()


@cli.command("backfill-oddalerts-history")
@click.option("--competition-id", required=True, type=int, help="OddAlerts competition id")
@click.option("--season-id", "season_ids", multiple=True, required=True, type=int, help="OddAlerts season id (repeatable)")
@click.option("--date-from", required=True, help="Start date YYYY-MM-DD")
@click.option("--date-to", required=True, help="End date YYYY-MM-DD")
@click.option("--league-name", default=None, help="Local league name override")
@click.option("--league-country", default=None, help="Local league country override")
@click.option("--bookmaker-id", "bookmaker_ids", multiple=True, type=int, default=(1, 2, 3, 4), help="OddAlerts bookmaker id (repeatable)")
@click.option("--apply", is_flag=True, help="Persist changes. Without this flag the import rolls back after validation.")
def backfill_oddalerts_history(
    competition_id: int,
    season_ids: tuple[int, ...],
    date_from: str,
    date_to: str,
    league_name: str | None,
    league_country: str | None,
    bookmaker_ids: tuple[int, ...],
    apply: bool,
):
    """Backfill historical ML and team-total 1.5 odds from OddAlerts."""
    from app.collector.oddalerts_api import OddAlertsClient
    from app.config import settings
    from app.oddalerts_backfill import OddAlertsHistoricalOddsBackfill

    if not settings.oddalerts_api_key:
        raise click.ClickException("ODDALERTS_API_KEY is not set.")

    session = get_session()
    try:
        stats = OddAlertsHistoricalOddsBackfill(
            session,
            OddAlertsClient(settings.oddalerts_api_key),
        ).run(
            competition_id=competition_id,
            season_ids=season_ids,
            date_from=_parse_utc_date_start(date_from),
            date_to=_parse_utc_date_end(date_to),
            league_name=league_name,
            league_country=league_country,
            bookmakers=bookmaker_ids,
        )

        if apply:
            session.commit()
        else:
            session.rollback()

        click.echo(
            f"{'Applied' if apply else 'Dry-run complete'}: "
            f"{stats.fixtures_seen} fixtures, {stats.fixtures_with_odds} with odds, "
            f"{stats.fixtures_created} fixtures created, {stats.fixtures_matched} fixtures matched, "
            f"{stats.teams_created} teams created, "
            f"{stats.results_created} results created, {stats.results_updated} results updated, "
            f"{stats.bundles_created} bundles created, {stats.bundles_updated} bundles updated, "
            f"{stats.odds_rows_seen} odds rows seen, {stats.skipped_rows} skipped."
        )
    finally:
        session.close()


@cli.command("build-favorite-sgp-backtest")
@click.option("--date-from", default=None, help="Optional start date YYYY-MM-DD")
@click.option("--date-to", default=None, help="Optional end date YYYY-MM-DD")
@click.option("--league-name", default=None, help="Optional local league name filter")
@click.option("--league-country", default=None, help="Optional local league country filter")
@click.option("--apply", is_flag=True, help="Persist changes. Without this flag the build rolls back after validation.")
def build_favorite_sgp_backtest(
    date_from: str | None,
    date_to: str | None,
    league_name: str | None,
    league_country: str | None,
    apply: bool,
):
    """Build favorite-side ML + team-total SGP rows for backtesting."""
    from app.favorite_sgp_backfill import FavoriteSgpBacktestBuilder

    session = get_session()
    try:
        stats = FavoriteSgpBacktestBuilder(session).run(
            league_name=league_name,
            league_country=league_country,
            date_from=_parse_utc_date_start(date_from) if date_from else None,
            date_to=_parse_utc_date_end(date_to) if date_to else None,
        )

        if apply:
            session.commit()
        else:
            session.rollback()

        click.echo(
            f"{'Applied' if apply else 'Dry-run complete'}: "
            f"{stats.bundles_seen} bundles seen, "
            f"{stats.rows_created} rows created, "
            f"{stats.rows_updated} rows updated, "
            f"{stats.rows_deleted} rows deleted, "
            f"{stats.rows_skipped} rows skipped."
        )
    finally:
        session.close()


@cli.command()
def scheduler():
    """Start the scheduler (blocking — use as container entrypoint)."""
    from app.scheduler import start_scheduler
    from app.metrics import start_metrics_server
    start_metrics_server(port=9090)
    start_scheduler(model_classes=MODEL_CLASSES)


if __name__ == "__main__":
    cli()
