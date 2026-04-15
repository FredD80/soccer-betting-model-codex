import click
from app.db.connection import get_session
from app.db.models import Base
from app.db.connection import engine
from app.logging_config import configure_logging

configure_logging()

# Import all user-defined model classes here as they are added
MODEL_CLASSES = []  # e.g. [MyModelV1, MyModelV2]


@click.group()
def cli():
    """Soccer Betting Model CLI"""


@cli.command()
def migrate():
    """Run database migrations (creates tables)."""
    Base.metadata.create_all(engine)
    click.echo("Database tables created.")


@cli.command()
def seed():
    """Seed the database with the 6 supported leagues."""
    from app.db.models import League
    session = get_session()
    leagues = [
        {"name": "Premier League",   "country": "England", "espn_id": "eng.1",          "odds_api_key": "soccer_epl"},
        {"name": "La Liga",          "country": "Spain",   "espn_id": "esp.1",          "odds_api_key": "soccer_spain_la_liga"},
        {"name": "Bundesliga",       "country": "Germany", "espn_id": "ger.1",          "odds_api_key": "soccer_germany_bundesliga"},
        {"name": "Serie A",          "country": "Italy",   "espn_id": "ita.1",          "odds_api_key": "soccer_italy_serie_a"},
        {"name": "Ligue 1",          "country": "France",  "espn_id": "fra.1",          "odds_api_key": "soccer_france_ligue_one"},
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
        click.echo(f"Seeded {added} league(s). {6 - added} already existed.")
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
def scheduler():
    """Start the scheduler (blocking — use as container entrypoint)."""
    from app.scheduler import start_scheduler
    from app.metrics import start_metrics_server
    start_metrics_server(port=9090)
    start_scheduler(model_classes=MODEL_CLASSES)


if __name__ == "__main__":
    cli()
