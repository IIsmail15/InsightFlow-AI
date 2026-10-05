"""Real PostgreSQL tests. Fixture changes always roll back; requires a seeded demo DB."""
import os
import unittest
from decimal import Decimal

from scripts.generate_data import COLUMNS, ROOT

ENABLED = os.environ.get("RUN_DATABASE_TESTS") == "1"
if ENABLED:
    import psycopg
    from psycopg import sql
    from scripts.seed_database import verify_data


@unittest.skipUnless(ENABLED, "Set RUN_DATABASE_TESTS=1 with a seeded PostgreSQL database")
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(os.environ.get("DATABASE_URL", ""))
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.conn.execute("SET LOCAL lock_timeout = '5s'")
        self.conn.execute(sql.SQL("TRUNCATE {}").format(
            sql.SQL(", ").join(sql.Identifier(t) for t in (*COLUMNS, "dataset_metadata"))))
        self.conn.execute("""
            INSERT INTO dataset_metadata VALUES (1, 42, '2025-12-01', '2026-04-01', 'GBP', 'fixture');
            INSERT INTO regions VALUES (1, 'North', 'Manager');
            INSERT INTO sales_representatives VALUES (1, 'Rep', 1);
            INSERT INTO customers
            SELECT n, 'Company ' || n, 'enterprise', 1, 1, '2025-12-01', 'organic', 'active'
            FROM generate_series(1, 4) n;
            INSERT INTO products VALUES (1, 'One', 'service', 40), (2, 'Two', 'service', 30);
            INSERT INTO subscriptions VALUES
              (1, 1, 'enterprise', 100, '2025-12-15', '2026-01-01', 'cancelled'),
              (2, 2, 'enterprise', 200, '2026-01-01', '2026-02-01', 'cancelled'),
              (3, 3, 'enterprise', 300, '2026-01-10', '2026-01-20', 'cancelled'),
              (4, 4, 'enterprise', 400, '2025-12-15', NULL, 'active');
            INSERT INTO orders VALUES
              (1, 1, '2026-01-10', 'completed', 100, 1),
              (2, 2, '2026-01-20', 'completed', 300, 1),
              (3, 3, '2026-01-22', 'cancelled', 999, 1);
            INSERT INTO order_items VALUES (1, 1, 1, 1, 40), (2, 1, 2, 2, 30),
              (3, 2, 1, 3, 100), (4, 3, 1, 1, 999);
            INSERT INTO payments VALUES
              (1, 1, 1, NULL, '2026-01-10', 100, 'completed'),
              (2, 2, 2, NULL, '2026-01-20', 300, 'completed'),
              (3, 3, 3, NULL, '2026-01-22', 999, 'failed');
            INSERT INTO refunds VALUES (1, 1, '2026-01-15', 40, 'not_needed'),
              (2, 2, '2026-02-05', 20, 'service_issue');
        """)

    def row(self, view, month="2026-01-01"):
        query = sql.SQL("SELECT * FROM analytics.{} WHERE month_start = %s").format(sql.Identifier(view))
        return self.conn.execute(query, (month,)).fetchone()

    def test_cash_revenue_aov_and_refunds_without_join_fanout(self):
        self.assertEqual(self.row("monthly_revenue")[1], Decimal("400"))
        self.assertEqual(self.row("monthly_average_order_value")[1:], (2, Decimal("400"), Decimal("200")))
        self.assertEqual(self.row("monthly_refund_rate")[1:], (Decimal("40"), Decimal("400"), Decimal("0.1")))

    def test_historical_mrr_and_churn_boundaries(self):
        self.assertEqual(self.row("monthly_mrr")[1], Decimal("600"))
        self.assertEqual(self.row("monthly_mrr", "2026-02-01")[1], Decimal("400"))
        self.assertEqual(self.row("monthly_customer_churn")[1:], (2, 1, Decimal("0.5")))
        self.assertEqual(self.row("monthly_customer_churn", "2026-02-01")[1:], (2, 1, Decimal("0.5")))
        self.assertEqual(self.row("monthly_customer_churn", "2026-03-01")[1:], (1, 0, Decimal("0")))

    def test_empty_months_and_cross_month_refund(self):
        self.assertEqual(self.row("monthly_revenue", "2026-02-01")[1], 0)
        self.assertIsNone(self.row("monthly_average_order_value", "2026-02-01")[-1])
        self.assertEqual(self.row("monthly_refund_rate", "2026-02-01")[1:], (Decimal("20"), Decimal("0"), None))
        self.assertIsNone(self.row("monthly_customer_churn", "2025-12-01")[-1])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM analytics.months").fetchone()[0], 4)

    def test_constraints_reject_wrong_customer_and_ambiguous_payment(self):
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with self.conn.transaction():
                self.conn.execute("INSERT INTO payments VALUES (4, 2, 1, NULL, '2026-01-10', 100, 'failed')")
        with self.assertRaises(psycopg.errors.CheckViolation):
            with self.conn.transaction():
                self.conn.execute("INSERT INTO payments VALUES (4, 1, 1, 1, '2026-01-10', 100, 'failed')")

    def test_cross_table_checks_detect_invalid_amounts(self):
        verify_data(self.conn)
        self.conn.execute("UPDATE orders SET total_amount = 99 WHERE order_id = 1")
        with self.assertRaisesRegex(ValueError, "order_totals"):
            verify_data(self.conn)

    def test_metadata_views_and_columns_exist(self):
        import json
        metadata = json.loads((ROOT / "backend/app/metadata/metrics.json").read_text())
        for metric in metadata["metrics"]:
            schema, view = metric["view"].split(".")
            self.conn.execute(sql.SQL("SELECT {} FROM {}.{} LIMIT 1").format(
                sql.Identifier(metric["value_column"]), sql.Identifier(schema), sql.Identifier(view)))


@unittest.skipUnless(ENABLED, "Set RUN_DATABASE_TESTS=1 with a seeded PostgreSQL database")
class SeedSafetyTests(unittest.TestCase):
    def snapshot(self):
        with psycopg.connect(os.environ.get("DATABASE_URL", "")) as conn:
            metadata = conn.execute("SELECT content_hash, random_seed FROM dataset_metadata").fetchone()
            counts = {table: conn.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
                      for table in COLUMNS}
            cash = conn.execute("SELECT SUM(amount) FROM payments").fetchone()[0]
            return metadata, counts, cash

    def test_failed_replacement_rolls_back(self):
        from scripts.generate_data import generate_dataset, csv_text, manifest_for
        from scripts.seed_database import seed_database
        before = self.snapshot()
        data, _ = generate_dataset(customer_count=10)
        data["orders"][0]["total_amount"] += Decimal("1")
        manifest = manifest_for(data, 42)
        payloads = {table: csv_text(table, rows).encode("utf-8") for table, rows in data.items()}
        with self.assertRaisesRegex(ValueError, "order_totals"):
            seed_database(payloads, manifest, replace=True)
        self.assertEqual(self.snapshot(), before)

    def test_repeat_seed_is_idempotent(self):
        from scripts.generate_data import generate_dataset, csv_text
        from scripts.seed_database import seed_database
        before = self.snapshot()
        data, manifest = generate_dataset(before[1]["customers"], before[0][1])
        if manifest["content_hash"] != before[0][0]:
            self.skipTest("Database was loaded from a custom CSV dataset")
        payloads = {table: csv_text(table, rows).encode("utf-8") for table, rows in data.items()}
        seed_database(payloads, manifest)
        self.assertEqual(self.snapshot(), before)

    def test_csv_tampering_is_rejected(self):
        import tempfile
        from pathlib import Path
        from scripts.generate_data import generate_dataset, write_dataset
        from scripts.seed_database import read_dataset
        data, manifest = generate_dataset(customer_count=2)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            write_dataset(data, manifest, directory)
            _, loaded = read_dataset(directory)
            self.assertEqual(loaded, manifest)
            with (directory / "customers.csv").open("a", encoding="utf-8") as stream:
                stream.write("invalid,row\n")
            with self.assertRaisesRegex(ValueError, "Checksum mismatch"):
                read_dataset(directory)


if __name__ == "__main__":
    unittest.main()
