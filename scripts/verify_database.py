"""Check seeded integrity, report five monthly metrics, and optionally assert demo events."""
import argparse
import json
import os
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row

try:
    from .generate_data import ROOT
    from .seed_database import verify_data
except ImportError:
    from generate_data import ROOT
    from seed_database import verify_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assert-events", action="store_true", help="Assert default 1,200-customer event thresholds")
    args = parser.parse_args()
    with psycopg.connect(os.environ.get("DATABASE_URL", ""), connect_timeout=10) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '30s'")
        verify_data(conn)
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""SELECT r.month_start, r.revenue, m.mrr, a.average_order_value,
                f.refund_rate, c.churn_rate
                FROM analytics.monthly_revenue r
                JOIN analytics.monthly_mrr m USING (month_start)
                JOIN analytics.monthly_average_order_value a USING (month_start)
                JOIN analytics.monthly_refund_rate f USING (month_start)
                JOIN analytics.monthly_customer_churn c USING (month_start)
                ORDER BY month_start DESC LIMIT 3""")
            metrics = cursor.fetchall()
            cursor.execute((ROOT / "database/event_evidence.sql").read_text(encoding="utf-8"))
            evidence = cursor.fetchall()
        if args.assert_events:
            events = {row["event"]: row for row in evidence}
            north, refunds, churn = (events[key] for key in ("north_revenue", "refund_rate", "enterprise_churn"))
            checks = {
                "north_revenue": north["observed"] < north["baseline"] * Decimal("0.6"),
                "refund_rate": refunds["observed"] > refunds["baseline"] * 2,
                "enterprise_churn": churn["observed"] > Decimal("0.20") and churn["observed"] - churn["baseline"] > Decimal("0.15"),
            }
            if not all(checks.values()):
                raise ValueError(f"Event thresholds failed: {checks}")
        print(json.dumps({"integrity": "passed", "recent_metrics": metrics, "event_evidence": evidence}, default=str, indent=2))


if __name__ == "__main__":
    main()
