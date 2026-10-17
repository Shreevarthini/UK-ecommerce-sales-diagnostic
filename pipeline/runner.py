"""Run the whole pipeline: raw data -> clean -> SQLite star schema -> SQL aggregates."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .clean import clean_transactions, write_quality_report
from .warehouse import build_warehouse, reconcile, run_analysis


def run(raw: pd.DataFrame,
        db_path: str | Path = "data/warehouse/ecommerce.db",
        processed_dir: str | Path = "data/processed",
        reports_dir: str | Path = "reports",
        drop_duplicates: bool = True):
    """Returns (clean_df, quality_report, sql_results, reconciliation_rows)."""
    clean_df, report = clean_transactions(raw, drop_duplicates=drop_duplicates)
    build_warehouse(clean_df, db_path)
    results = run_analysis(db_path, processed_dir)
    checks = reconcile(clean_df, results)
    write_quality_report(report, reports_dir)
    return clean_df, report, results, checks