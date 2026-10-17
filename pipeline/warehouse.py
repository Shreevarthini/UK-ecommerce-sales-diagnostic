"""Step 2 - load the cleaned data into a SQLite star schema, then run the SQL
aggregation queries and reconcile them against pandas."""
from __future__ import annotations

import math
import re
import sqlite3
from pathlib import Path

import pandas as pd

from .clean import GUEST_CUSTOMER

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"
SCHEMA_SQL = SQL_DIR / "schema.sql"
ANALYSIS_SQL = SQL_DIR / "analysis.sql"


def _mode(series: pd.Series) -> str:
    modes = series.mode()
    return modes.iat[0] if len(modes) else "UNKNOWN"


def build_warehouse(df: pd.DataFrame, db_path: str | Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    countries = pd.DataFrame({"country": sorted(df["country"].unique())})
    countries["country_id"] = range(1, len(countries) + 1)

    # product names can vary per product number in raw data -> keep the most common one
    products = df.groupby("product_no")["product_name"].agg(_mode).reset_index()
    products["product_id"] = range(1, len(products) + 1)

    customers = pd.DataFrame({"customer_no": sorted(df["customer_no"].unique())})
    customers["customer_id"] = range(1, len(customers) + 1)
    customers["is_guest"] = (customers["customer_no"] == GUEST_CUSTOMER).astype(int)

    days = df["date"].dt.normalize().drop_duplicates().sort_values().reset_index(drop=True)
    dates = pd.DataFrame({
        "date_id": days.dt.strftime("%Y%m%d").astype(int),
        "full_date": days.dt.strftime("%Y-%m-%d"),
        "year": days.dt.year,
        "month": days.dt.month,
        "quarter": days.dt.quarter,
        "day_of_week": days.dt.dayofweek,
    })

    fact = (
        df.assign(full_date=df["date"].dt.strftime("%Y-%m-%d"))
        .merge(dates[["full_date", "date_id"]], on="full_date")
        .merge(products[["product_no", "product_id"]], on="product_no")
        .merge(customers[["customer_no", "customer_id"]], on="customer_no")
        .merge(countries, on="country")
    )
    if len(fact) != len(df):
        raise RuntimeError("Dimension join changed the row count - check for duplicate dimension keys.")
    fact = fact[["transaction_no", "date_id", "product_id", "customer_id", "country_id",
                 "quantity", "unit_price", "sales", "is_cancelled"]]

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_SQL.read_text())
        countries[["country_id", "country"]].to_sql("dim_country", conn, if_exists="append", index=False)
        products[["product_id", "product_no", "product_name"]].to_sql("dim_product", conn, if_exists="append", index=False)
        customers[["customer_id", "customer_no", "is_guest"]].to_sql("dim_customer", conn, if_exists="append", index=False)
        dates.to_sql("dim_date", conn, if_exists="append", index=False)
        fact.to_sql("fact_order_line", conn, if_exists="append", index=False, chunksize=50_000)
        conn.commit()
    finally:
        conn.close()


def load_named_queries(sql_path: str | Path = ANALYSIS_SQL) -> dict[str, str]:
    queries: dict[str, list[str]] = {}
    name = None
    for line in Path(sql_path).read_text().splitlines():
        match = re.match(r"--\s*name:\s*(\w+)", line)
        if match:
            name = match.group(1)
            queries[name] = []
        elif name is not None:
            queries[name].append(line)
    return {k: "\n".join(v).strip() for k, v in queries.items()}


def run_analysis(db_path: str | Path, out_dir: str | Path | None = None,
                 sql_path: str | Path = ANALYSIS_SQL) -> dict[str, pd.DataFrame]:
    results: dict[str, pd.DataFrame] = {}
    conn = sqlite3.connect(db_path)
    try:
        for name, query in load_named_queries(sql_path).items():
            results[name] = pd.read_sql_query(query, conn)
    finally:
        conn.close()
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in results.items():
            frame.to_csv(out_dir / f"{name}.csv", index=False)
    return results


def foreign_key_violations(db_path: str | Path) -> list:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()


def reconcile(clean_df: pd.DataFrame, results: dict[str, pd.DataFrame]) -> list[dict]:
    """Compare pandas totals with the SQL output. Returns one dict per check."""
    completed = clean_df[clean_df["is_cancelled"] == 0]
    pandas_revenue = float(completed["sales"].sum())
    pandas_orders = int(completed["transaction_no"].nunique())
    kpi = results["kpi_summary"].iloc[0]

    def check(name, expected, actual, tol=0.05):
        ok = math.isclose(float(expected), float(actual), abs_tol=tol)
        return {"check": name, "pandas": round(float(expected), 2), "sql": round(float(actual), 2), "ok": ok}

    return [
        check("Total revenue (KPI)", pandas_revenue, kpi["total_revenue"], tol=0.01),
        check("Completed transactions (KPI)", pandas_orders, kpi["completed_transactions"], tol=0),
        check("Sum of monthly revenue", pandas_revenue, results["monthly_revenue"]["revenue"].sum()),
        check("Final running revenue", pandas_revenue, results["monthly_revenue"]["running_revenue"].iloc[-1]),
        check("Sum of country revenue", pandas_revenue, results["country_summary"]["revenue"].sum(), tol=0.5),
        check("Sum of product revenue", pandas_revenue, results["product_pareto"]["revenue"].sum(), tol=0.5),
        check("Product Pareto ends at 100%", 100.0, results["product_pareto"]["cumulative_pct"].iloc[-1], tol=0.05),
    ]
