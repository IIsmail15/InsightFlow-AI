import csv
import io
import json
import tempfile
import unittest
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from scripts.generate_data import COLUMNS, END, ROOT, START, csv_text, generate_dataset, write_dataset


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.manifest = generate_dataset()

    def test_reproducibility_and_seed_variation(self):
        _, repeated = generate_dataset()
        self.assertEqual(self.manifest, repeated)
        _, different = generate_dataset(seed=43)
        self.assertNotEqual(self.manifest["content_hash"], different["content_hash"])

    def test_money_relationships_and_timelines(self):
        data = self.data
        customers = {c["customer_id"]: c for c in data["customers"]}
        orders = {o["order_id"]: o for o in data["orders"]}
        subscriptions = {s["subscription_id"]: s for s in data["subscriptions"]}
        payments = {p["payment_id"]: p for p in data["payments"]}
        totals = defaultdict(Decimal)
        for item in data["order_items"]:
            totals[item["order_id"]] += item["quantity"] * item["unit_price"]
        for order in orders.values():
            self.assertEqual(totals[order["order_id"]], order["total_amount"])
            self.assertGreaterEqual(order["order_date"], customers[order["customer_id"]]["signup_date"])
        paid_orders = set()
        for payment in payments.values():
            self.assertNotEqual(payment["order_id"] is None, payment["subscription_id"] is None)
            self.assertTrue(START <= payment["payment_date"] < END)
            if payment["order_id"]:
                order = orders[payment["order_id"]]
                self.assertEqual(payment["customer_id"], order["customer_id"])
                self.assertEqual(payment["amount"], order["total_amount"])
                if payment["payment_status"] == "completed":
                    self.assertEqual(order["status"], "completed")
                    self.assertNotIn(order["order_id"], paid_orders)
                    paid_orders.add(order["order_id"])
            else:
                sub = subscriptions[payment["subscription_id"]]
                self.assertEqual(payment["customer_id"], sub["customer_id"])
                self.assertGreaterEqual(payment["payment_date"], sub["start_date"])
                self.assertTrue(sub["end_date"] is None or payment["payment_date"] < sub["end_date"])
        self.assertEqual(paid_orders, {o["order_id"] for o in orders.values() if o["status"] == "completed"})
        for refund in data["refunds"]:
            payment = payments[refund["payment_id"]]
            self.assertEqual(payment["payment_status"], "completed")
            self.assertIsNotNone(payment["order_id"])
            self.assertLessEqual(refund["amount"], payment["amount"])
            self.assertTrue(payment["payment_date"] <= refund["refund_date"] < END)

    def test_three_discoverable_events(self):
        customers = {c["customer_id"]: c for c in self.data["customers"]}
        revenue, north, refunds = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
        for p in self.data["payments"]:
            if p["payment_status"] == "completed":
                month = p["payment_date"].replace(day=1)
                revenue[month] += p["amount"]
                if customers[p["customer_id"]]["region_id"] == 1:
                    north[month] += p["amount"]
        for r in self.data["refunds"]:
            refunds[r["refund_date"].replace(day=1)] += r["amount"]
        before = sum(north[date(2026, m, 1)] for m in (4, 5, 6))
        after = sum(north[date(2026, m, 1)] for m in (7, 8, 9))
        self.assertLess(after / before, Decimal("0.6"))
        rates = []
        for period in ((6, 7), (8, 9)):
            rates.append(sum(refunds[date(2026, m, 1)] for m in period)
                         / sum(revenue[date(2026, m, 1)] for m in period))
        self.assertGreater(rates[1], rates[0] * 2)
        churn = []
        for month in (8, 9):
            opening = [s for s in self.data["subscriptions"]
                       if customers[s["customer_id"]]["segment"] == "enterprise"
                       and s["start_date"] < date(2026, month, 1)
                       and (s["end_date"] is None or s["end_date"] >= date(2026, month, 1))]
            churn.append(sum(s["end_date"] is not None and s["end_date"] < date(2026, month + 1, 1)
                             for s in opening) / len(opening))
        self.assertGreater(churn[1], 0.20)
        self.assertGreater(churn[1], churn[0] + 0.15)

    def test_csv_manifest_and_small_dataset(self):
        data, manifest = generate_dataset(customer_count=1)
        with tempfile.TemporaryDirectory() as temp:
            write_dataset(data, manifest, temp)
            written = json.loads((Path(temp) / "manifest.json").read_text())
            self.assertEqual(written, manifest)
            for table, columns in COLUMNS.items():
                reader = csv.DictReader(io.StringIO(csv_text(table, data[table])))
                self.assertEqual(tuple(reader.fieldnames), columns)
                self.assertEqual(len(list(reader)), manifest["row_counts"][table])
        with self.assertRaises(ValueError):
            generate_dataset(customer_count=0)

    def test_five_metric_contracts(self):
        metadata = json.loads((ROOT / "backend/app/metadata/metrics.json").read_text())
        self.assertEqual(len(metadata["metrics"]), 5)
        for metric in metadata["metrics"]:
            self.assertTrue({"name", "description", "formula", "source_tables", "dimensions", "allowed_filters", "view", "value_column"} <= metric.keys())


if __name__ == "__main__":
    unittest.main()
