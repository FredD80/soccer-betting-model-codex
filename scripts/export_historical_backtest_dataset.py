#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db.connection import get_session
from app.db.models import (
    FavoriteSgpBacktestRow,
    Fixture,
    HistoricalOddsBundle,
    League,
    Result,
    Team,
    TeamAlias,
)

EXPORT_DIR = ROOT / "data" / "db_exports"
CSV_DIR = EXPORT_DIR / "csv"
SQL_PATH = EXPORT_DIR / "historical_backtest_dataset_restore.sql"
MANIFEST_PATH = EXPORT_DIR / "manifest.json"


def _csv_value(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _copy_value(value):
    if value is None:
        return r"\N"
    if isinstance(value, datetime):
        text = value.isoformat(sep=" ")
    elif isinstance(value, (date, time)):
        text = value.isoformat()
    elif isinstance(value, bool):
        text = "t" if value else "f"
    else:
        text = str(value)
    return (
        text.replace("\\", "\\\\")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def _row_dict(model, row) -> dict[str, object]:
    return {column.name: getattr(row, column.name) for column in model.__table__.columns}


def _write_csv(path: Path, model, rows: list[object]) -> None:
    columns = [column.name for column in model.__table__.columns]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            raw = _row_dict(model, row)
            writer.writerow({key: _csv_value(value) for key, value in raw.items()})


def _write_copy_block(fh, table_name: str, model, rows: list[object]) -> None:
    columns = [column.name for column in model.__table__.columns]
    fh.write(f"COPY public.{table_name} ({', '.join(columns)}) FROM stdin;\n")
    for row in rows:
        raw = _row_dict(model, row)
        values = [_copy_value(raw[column]) for column in columns]
        fh.write("\t".join(values))
        fh.write("\n")
    fh.write("\\.\n\n")


def _write_sequence_setval(fh, table_name: str) -> None:
    fh.write(
        "SELECT pg_catalog.setval("
        f"'public.{table_name}_id_seq', "
        f"COALESCE((SELECT MAX(id) FROM public.{table_name}), 1), "
        "true"
        ");\n"
    )


def export() -> dict[str, object]:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    CSV_DIR.mkdir(parents=True, exist_ok=True)

    session = get_session()
    try:
        bundle_rows = session.execute(
            select(HistoricalOddsBundle).order_by(HistoricalOddsBundle.id)
        ).scalars().all()
        bundle_ids = [row.id for row in bundle_rows]
        fixture_ids = sorted({row.fixture_id for row in bundle_rows})

        favorite_rows = session.execute(
            select(FavoriteSgpBacktestRow)
            .filter(FavoriteSgpBacktestRow.historical_bundle_id.in_(bundle_ids))
            .order_by(FavoriteSgpBacktestRow.id)
        ).scalars().all() if bundle_ids else []

        fixture_rows = session.execute(
            select(Fixture)
            .filter(Fixture.id.in_(fixture_ids))
            .order_by(Fixture.id)
        ).scalars().all() if fixture_ids else []

        result_rows = session.execute(
            select(Result)
            .filter(Result.fixture_id.in_(fixture_ids))
            .order_by(Result.id)
        ).scalars().all() if fixture_ids else []

        league_ids = sorted({row.league_id for row in fixture_rows})
        team_ids = sorted(
            {row.home_team_id for row in fixture_rows}
            | {row.away_team_id for row in fixture_rows}
        )

        league_rows = session.execute(
            select(League)
            .filter(League.id.in_(league_ids))
            .order_by(League.id)
        ).scalars().all() if league_ids else []

        team_rows = session.execute(
            select(Team)
            .filter(Team.id.in_(team_ids))
            .order_by(Team.id)
        ).scalars().all() if team_ids else []

        alias_rows = session.execute(
            select(TeamAlias)
            .filter(TeamAlias.team_id.in_(team_ids))
            .order_by(TeamAlias.id)
        ).scalars().all() if team_ids else []

        table_rows = [
            ("leagues", League, league_rows),
            ("teams", Team, team_rows),
            ("team_aliases", TeamAlias, alias_rows),
            ("fixtures", Fixture, fixture_rows),
            ("results", Result, result_rows),
            ("historical_odds_bundles", HistoricalOddsBundle, bundle_rows),
            ("favorite_sgp_backtest_rows", FavoriteSgpBacktestRow, favorite_rows),
        ]

        for table_name, model, rows in table_rows:
            _write_csv(CSV_DIR / f"{table_name}.csv", model, rows)

        with SQL_PATH.open("w") as fh:
            generated_at = datetime.now(timezone.utc).isoformat()
            fh.write("-- Historical backtest dataset restore file\n")
            fh.write(f"-- Generated at {generated_at}\n")
            fh.write("-- Run the repo migrations first, then restore this into a fresh Postgres database.\n")
            fh.write("-- WARNING: this file truncates the exported tables before loading data.\n\n")
            fh.write("BEGIN;\n")
            fh.write(
                "TRUNCATE TABLE "
                "public.favorite_sgp_backtest_rows, "
                "public.historical_odds_bundles, "
                "public.results, "
                "public.team_aliases, "
                "public.fixtures, "
                "public.teams, "
                "public.leagues "
                "RESTART IDENTITY CASCADE;\n\n"
            )
            for table_name, model, rows in table_rows:
                _write_copy_block(fh, table_name, model, rows)
            for table_name in (
                "leagues",
                "teams",
                "team_aliases",
                "fixtures",
                "results",
                "historical_odds_bundles",
                "favorite_sgp_backtest_rows",
            ):
                _write_sequence_setval(fh, table_name)
            fh.write("\nCOMMIT;\n")

        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "export_root": str(EXPORT_DIR.relative_to(ROOT)),
            "tables": {
                table_name: {
                    "rows": len(rows),
                    "csv": str((CSV_DIR / f"{table_name}.csv").relative_to(ROOT)),
                }
                for table_name, _model, rows in table_rows
            },
            "sql_restore": str(SQL_PATH.relative_to(ROOT)),
            "league_scope": [
                {"id": row.id, "name": row.name, "country": row.country}
                for row in league_rows
            ],
        }
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
        return manifest
    finally:
        session.close()


if __name__ == "__main__":
    manifest = export()
    print(json.dumps(manifest, indent=2))
