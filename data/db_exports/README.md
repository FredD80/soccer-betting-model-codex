# Historical Backtest Exports

This directory contains a repo-local export of the odds-backed backtesting dataset.

Files:
- `csv/`: filtered table exports for the leagues and fixtures referenced by `historical_odds_bundles`
- `historical_backtest_dataset_restore.sql`: PostgreSQL data restore script for the exported tables
- `manifest.json`: row counts and file inventory

Restore flow:
1. Run the repo migrations against a fresh Postgres database.
2. Apply `historical_backtest_dataset_restore.sql`.

Caveat:
- The SQL restore file truncates the exported tables before loading data. Use it against a fresh or disposable database, not a live shared one.
