"""Step 1 - clean the raw UK e-commerce transactions with pandas.

Every rule below is counted, so the data-quality report shows exactly what was
found and removed (nothing is silently dropped).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = [
    "TransactionNo", "Date", "ProductNo", "ProductName",
    "Price", "Quantity", "CustomerNo", "Country",
]
GUEST_CUSTOMER = "GUEST"
MISSING_CUSTOMER_TOKENS = {"", "-1", "nan", "none", "null"}


def load_raw(path: str | Path) -> pd.DataFrame:
    """Read the raw CSV as text so no value is silently coerced on load."""
    df = pd.read_csv(path, dtype=str)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Raw file is missing columns {missing}. Found: {list(df.columns)}. "
            "Rename the columns in your CSV or edit REQUIRED_COLUMNS in pipeline/clean.py."
        )
    return df[REQUIRED_COLUMNS]


def _normalise_customer(series: pd.Series) -> pd.Series:
    s = series.astype("string").str.strip()
    s = s.str.replace(r"\.0$", "", regex=True)  # '17850.0' -> '17850'
    missing = s.isna() | s.str.lower().isin(MISSING_CUSTOMER_TOKENS)
    return s.mask(missing, GUEST_CUSTOMER)


def clean_transactions(raw: pd.DataFrame, drop_duplicates: bool = True) -> tuple[pd.DataFrame, dict]:
    """Return (clean dataframe in snake_case, data-quality report dict).

    drop_duplicates=False keeps exact duplicate lines (the raw data has no line ID,
    so identical lines can be genuine repeat scans). They are still counted.
    """
    report: dict = {"raw_rows": int(len(raw))}
    df = raw.copy()

    # 1. exact duplicate rows (checked on the raw text values)
    report["duplicate_rows_found"] = int(df.duplicated().sum())
    if drop_duplicates:
        df = df.drop_duplicates()
        report["duplicate_rows_removed"] = report["duplicate_rows_found"]
    else:
        report["duplicate_rows_removed"] = 0

    # 2. unparseable dates
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    bad_dates = df["Date"].isna()
    report["invalid_dates_removed"] = int(bad_dates.sum())
    df = df[~bad_dates]

    # 3. non-numeric price / quantity
    df = df.assign(
        Price=pd.to_numeric(df["Price"], errors="coerce"),
        Quantity=pd.to_numeric(df["Quantity"], errors="coerce"),
    )
    bad_numbers = df["Price"].isna() | df["Quantity"].isna()
    report["non_numeric_price_or_quantity_removed"] = int(bad_numbers.sum())
    df = df[~bad_numbers]

    # 4. zero / negative prices (stock adjustments, not sales)
    bad_price = df["Price"] <= 0
    report["zero_or_negative_price_removed"] = int(bad_price.sum())
    df = df[~bad_price]

    # 5. text columns: trim, fill gaps
    for col in ("TransactionNo", "ProductNo", "ProductName", "Country"):
        df[col] = df[col].astype("string").str.strip()
    df["ProductNo"] = df["ProductNo"].fillna("UNKNOWN")
    df["ProductName"] = df["ProductName"].fillna("UNKNOWN")
    df["Country"] = df["Country"].fillna("Unknown")

    # 6. missing customer ids -> GUEST (keeps guest revenue, like the IFNULL in Tableau)
    customers = _normalise_customer(df["CustomerNo"])
    report["missing_customer_filled_as_guest"] = int((customers == GUEST_CUSTOMER).sum())
    df["CustomerNo"] = customers

    # 7. cancellations: 'C' prefix or negative quantity
    is_cancelled = df["TransactionNo"].str.upper().str.startswith("C") | (df["Quantity"] < 0)

    out = pd.DataFrame({
        "transaction_no": df["TransactionNo"].astype(object),
        "date": df["Date"],
        "product_no": df["ProductNo"].astype(object),
        "product_name": df["ProductName"].astype(object),
        "customer_no": df["CustomerNo"].astype(object),
        "country": df["Country"].astype(object),
        "quantity": df["Quantity"].round().astype(int),
        "unit_price": df["Price"].astype(float),
        "is_cancelled": is_cancelled.astype(int),
    })
    out["sales"] = out["quantity"] * out["unit_price"]
    out = out.reset_index(drop=True)

    completed = out[out["is_cancelled"] == 0]
    report.update({
        "rows_after_cleaning": int(len(out)),
        "cancelled_lines": int(out["is_cancelled"].sum()),
        "completed_lines": int(len(completed)),
        "completed_transactions": int(completed["transaction_no"].nunique()),
        "completed_revenue": round(float(completed["sales"].sum()), 2),
        "date_min": out["date"].min().strftime("%Y-%m-%d") if len(out) else None,
        "date_max": out["date"].max().strftime("%Y-%m-%d") if len(out) else None,
    })
    return out, report


def write_quality_report(report: dict, reports_dir: str | Path) -> None:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "data_quality_report.json").write_text(json.dumps(report, indent=2))

    lines = ["# Data quality report", "", "| Check | Count / value |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {v:,} |" if isinstance(v, (int, float)) and not isinstance(v, bool)
              else f"| {k.replace('_', ' ')} | {v} |" for k, v in report.items()]
    (reports_dir / "data_quality_report.md").write_text("\n".join(lines) + "\n")