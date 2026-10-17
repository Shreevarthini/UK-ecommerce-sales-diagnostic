"""Usage:  python run_pipeline.py --raw data/raw/sales_transactions.csv"""
import argparse
import sys

from pipeline.clean import load_raw
from pipeline.runner import run


def main() -> int:
    parser = argparse.ArgumentParser(description="UK e-commerce data pipeline")
    parser.add_argument("--raw", default="data/raw/sales_transactions.csv", help="path to the raw CSV")
    parser.add_argument("--db", default="data/warehouse/ecommerce.db")
    parser.add_argument("--out", default="data/processed", help="where aggregate CSVs for Tableau go")
    parser.add_argument("--reports", default="reports")
    parser.add_argument("--keep-duplicates", action="store_true",
                        help="keep exact duplicate lines (matches the Tableau dashboard)")
    args = parser.parse_args()

    raw = load_raw(args.raw)
    _, report, results, checks = run(raw, args.db, args.out, args.reports,
                              drop_duplicates=not args.keep_duplicates)

    print("\n=== Data quality report ===")
    for key, value in report.items():
        print(f"{key:45s} {value:>15,}" if isinstance(value, (int, float)) else f"{key:45s} {value:>15}")

    print("\n=== Reconciliation: pandas vs SQL ===")
    for c in checks:
        status = "OK  " if c["ok"] else "FAIL"
        print(f"[{status}] {c['check']:32s} pandas={c['pandas']:>16,.2f}  sql={c['sql']:>16,.2f}")

    print(f"\nKPIs from SQL:\n{results['kpi_summary'].to_string(index=False)}")
    print(f"\nAggregate CSVs written to {args.out}/ ; report written to {args.reports}/")
    return 0 if all(c["ok"] for c in checks) else 1


if __name__ == "__main__":
    sys.exit(main())