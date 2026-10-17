"""Tests use a tiny hand-built dataset, so CI needs no large CSV.

Expected numbers (worked out by hand):
  completed lines: T1 (10 + 6), T2 (25, guest), T3 (5 + 5), T7 (18)  -> revenue 69.00, 4 orders
  by month: Jan 41, Feb 10, Mar 18   by product: P1 40, P2 24, P3 5
  by country: UK 34, Germany 25, France 10
"""
import numpy as np
import pandas as pd
import pytest

from pipeline.clean import clean_transactions
from pipeline.runner import run
from pipeline.warehouse import foreign_key_violations

COLUMNS = ["TransactionNo", "Date", "ProductNo", "ProductName", "Price", "Quantity", "CustomerNo", "Country"]

ROWS = [
    ["T1", "1/5/2019", "P1", "Mug", "2.50", "4", "100", "United Kingdom"],
    ["T1", "1/5/2019", "P2", "Plate", "3.00", "2", "100", "United Kingdom"],
    ["T2", "1/20/2019", "P1", "Mug", "2.50", "10", None, "Germany"],            # guest customer
    ["T3", "2/3/2019", "P3", "Bowl", "5.00", "1", "101", "France"],
    ["T3", "2/3/2019", "P1", "Mug", "2.50", "2", "101", "France"],
    ["C4", "2/10/2019", "P1", "Mug", "2.50", "-3", "100", "United Kingdom"],    # cancellation
    ["T5", "2/15/2019", "P2", "Plate", "0", "5", "102", "United Kingdom"],      # zero price
    ["T6", "not-a-date", "P2", "Plate", "3.00", "1", "102", "United Kingdom"],  # bad date
    ["T3", "2/3/2019", "P3", "Bowl", "5.00", "1", "101", "France"],             # exact duplicate
    ["T7", "3/1/2019", "P2", "Plate", "3.00", "6", "100.0", "United Kingdom"],  # '100.0' -> '100'
    ["T8", "3/2/2019", "P3", "Bowl", "abc", "1", "101", "France"],              # non-numeric price
]


@pytest.fixture(scope="module")
def outputs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pipeline")
    raw = pd.DataFrame(ROWS, columns=COLUMNS)
    clean_df, report, results, checks = run(
        raw, tmp / "wh.db", tmp / "processed", tmp / "reports"
    )
    return {"clean": clean_df, "report": report, "results": results, "checks": checks,
            "db": tmp / "wh.db", "processed": tmp / "processed", "reports": tmp / "reports"}


# ---------- cleaning ----------
def test_cleaning_counts_every_issue(outputs):
    r = outputs["report"]
    assert r["raw_rows"] == 11
    assert r["duplicate_rows_found"] == 1
    assert r["duplicate_rows_removed"] == 1
    assert r["invalid_dates_removed"] == 1
    assert r["non_numeric_price_or_quantity_removed"] == 1
    assert r["zero_or_negative_price_removed"] == 1
    assert r["rows_after_cleaning"] == 7
    assert r["cancelled_lines"] == 1
    assert r["completed_transactions"] == 4
    assert r["completed_revenue"] == 69.00


def test_missing_customer_becomes_guest_and_ids_are_normalised(outputs):
    clean = outputs["clean"]
    assert (clean["customer_no"] == "GUEST").sum() == 1
    assert "100.0" not in set(clean["customer_no"])
    assert outputs["report"]["missing_customer_filled_as_guest"] == 1


def test_cancellation_flag(outputs):
    clean = outputs["clean"]
    cancelled = clean[clean["is_cancelled"] == 1]
    assert list(cancelled["transaction_no"]) == ["C4"]
    assert (cancelled["quantity"] < 0).all()


# ---------- warehouse integrity ----------
def test_no_foreign_key_violations(outputs):
    assert foreign_key_violations(outputs["db"]) == []


def test_fact_row_count_matches_clean_data(outputs):
    import sqlite3
    conn = sqlite3.connect(outputs["db"])
    n = conn.execute("SELECT COUNT(*) FROM fact_order_line").fetchone()[0]
    conn.close()
    assert n == len(outputs["clean"])


# ---------- SQL results vs hand calculation ----------
def test_kpis(outputs):
    kpi = outputs["results"]["kpi_summary"].iloc[0]
    assert kpi["total_revenue"] == pytest.approx(69.00)
    assert kpi["completed_transactions"] == 4
    assert kpi["avg_order_value"] == pytest.approx(17.25)


def test_monthly_revenue_growth_and_running_total(outputs):
    m = outputs["results"]["monthly_revenue"].set_index("month")
    assert m.loc["2019-01", "revenue"] == pytest.approx(41.0)
    assert m.loc["2019-02", "revenue"] == pytest.approx(10.0)
    assert m.loc["2019-03", "revenue"] == pytest.approx(18.0)
    assert np.isnan(m.loc["2019-01", "mom_growth_pct"])            # no previous month
    assert m.loc["2019-02", "mom_growth_pct"] == pytest.approx(-75.6, abs=0.05)
    assert m["running_revenue"].iloc[-1] == pytest.approx(69.0)


def test_product_pareto(outputs):
    p = outputs["results"]["product_pareto"]
    assert list(p["product_no"]) == ["P1", "P2", "P3"]
    assert list(p["revenue"]) == pytest.approx([40.0, 24.0, 5.0])
    assert p["cumulative_pct"].iloc[-1] == pytest.approx(100.0)
    assert p["share_pct"].iloc[0] == pytest.approx(57.97, abs=0.01)


def test_country_summary(outputs):
    c = outputs["results"]["country_summary"].set_index("country")
    assert c.loc["United Kingdom", "revenue"] == pytest.approx(34.0)
    assert c.loc["United Kingdom", "avg_order_value"] == pytest.approx(17.0)   # 34 / 2 orders
    assert c.loc["Germany", "revenue"] == pytest.approx(25.0)


def test_customer_segments_exclude_guests(outputs):
    seg = outputs["results"]["customer_segments"]
    assert "GUEST" not in set(seg["customer_no"])
    assert seg["revenue"].sum() == pytest.approx(69.0 - 25.0)       # total minus guest revenue
    assert seg.set_index("customer_no").loc["100", "revenue_quartile"] == 1


def test_cancellation_rate_by_month(outputs):
    c = outputs["results"]["cancellation_by_month"].set_index("month")
    assert c.loc["2019-02", "cancelled_orders"] == 1
    assert c.loc["2019-02", "completed_orders"] == 1
    assert c.loc["2019-02", "cancellation_rate_pct"] == pytest.approx(50.0)


# ---------- reconciliation + exports ----------
def test_all_reconciliation_checks_pass(outputs):
    failed = [c for c in outputs["checks"] if not c["ok"]]
    assert failed == []


def test_exports_written(outputs):
    for name in ["kpi_summary", "monthly_revenue", "product_pareto",
                 "customer_segments", "country_summary", "cancellation_by_month"]:
        assert (outputs["processed"] / f"{name}.csv").exists()
    assert (outputs["reports"] / "data_quality_report.md").exists()


def test_keep_duplicates_option():
    # keeping the duplicate T3 bowl line adds 5.00 of revenue; it is still counted as found
    _, report = clean_transactions(pd.DataFrame(ROWS, columns=COLUMNS), drop_duplicates=False)
    assert report["duplicate_rows_found"] == 1
    assert report["duplicate_rows_removed"] == 0
    assert report["completed_revenue"] == 74.00
    assert report["completed_transactions"] == 4