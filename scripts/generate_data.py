"""Generate repeatable GBP business records and inspectable CSV files (stdlib only)."""

import argparse
import calendar
import csv
import hashlib
import io
import json
import random
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = date(2025, 1, 1)
END = date(2026, 10, 1)  # exclusive; complete months only
GENERATOR_VERSION = 1
COLUMNS = {
    "regions": ("region_id", "region_name", "sales_manager"),
    "sales_representatives": ("sales_rep_id", "rep_name", "region_id"),
    "customers": ("customer_id", "company_name", "segment", "region_id", "sales_rep_id", "signup_date", "acquisition_channel", "status"),
    "products": ("product_id", "product_name", "category", "price"),
    "orders": ("order_id", "customer_id", "order_date", "status", "total_amount", "region_id"),
    "order_items": ("order_item_id", "order_id", "product_id", "quantity", "unit_price"),
    "subscriptions": ("subscription_id", "customer_id", "plan", "monthly_value", "start_date", "end_date", "status"),
    "payments": ("payment_id", "customer_id", "order_id", "subscription_id", "payment_date", "amount", "payment_status"),
    "refunds": ("refund_id", "payment_id", "refund_date", "amount", "reason"),
    "support_tickets": ("ticket_id", "customer_id", "created_at", "category", "priority", "status", "resolution_time_hours"),
}
EVENTS = [
    {"name": "North purchasing decline", "start": "2026-07-01", "dimension": "North",
     "mechanism": "Monthly order probability multiplied by 0.18; other regions unchanged.",
     "comparison": "North collected revenue: April-June versus July-September 2026."},
    {"name": "Analytics Export refund spike", "start": "2026-08-01", "dimension": "Analytics Export",
     "mechanism": "Refund probability on orders containing this product rises from 0.025 to 0.42; technical tickets accompany defects.",
     "comparison": "Refund amount rate: June-July versus August-September 2026."},
    {"name": "Enterprise churn increase", "start": "2026-09-01", "dimension": "enterprise",
     "mechanism": "Monthly cancellation probability rises from 0.012 to 0.38; cancellation tickets accompany exits.",
     "comparison": "Enterprise opening-cohort churn: August versus September 2026."},
]


def next_month(day):
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def months():
    current = START
    while current < END:
        yield current
        current = next_month(current)


def money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def csv_text(table, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS[table], lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def manifest_for(data, seed):
    checksums = {table: hashlib.sha256(csv_text(table, rows).encode("utf-8")).hexdigest()
                 for table, rows in data.items()}
    manifest = {
        "generator_version": GENERATOR_VERSION, "seed": seed,
        "observation_start": START.isoformat(), "observation_end": END.isoformat(),
        "currency": "GBP", "row_counts": {table: len(rows) for table, rows in data.items()},
        "sha256": checksums, "events": EVENTS,
    }
    manifest["content_hash"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()
    return manifest


def generate_dataset(customer_count=1200, seed=42):
    if customer_count < 1:
        raise ValueError("customer_count must be positive")
    rng = random.Random(seed)
    data = {table: [] for table in COLUMNS}

    def add(table, **fields):
        key = COLUMNS[table][0]
        row = {key: len(data[table]) + 1, **fields}
        data[table].append(row)
        return row

    def ticket(customer_id, created_at, category, priority="medium"):
        resolved = created_at < END - timedelta(days=5)
        add("support_tickets", customer_id=customer_id, created_at=created_at,
            category=category, priority=priority, status="resolved" if resolved else "open",
            resolution_time_hours=money(rng.uniform(2, 72)) if resolved else None)

    for name in ("North", "South", "Midlands", "Scotland"):
        region = add("regions", region_name=name, sales_manager=f"{name} Manager")
        for number in (1, 2):
            add("sales_representatives", rep_name=f"{name} Representative {number}",
                region_id=region["region_id"])
    for name, category, price in (
        ("Workspace Setup", "implementation", 800), ("Team Workshop", "training", 400),
        ("Analytics Export", "add_on", 250), ("Data Migration", "implementation", 1500),
        ("Reporting Audit", "consulting", 600), ("Premium Onboarding", "implementation", 1200),
    ):
        add("products", product_name=name, category=category, price=money(price))

    # Most customers join early; continued acquisition provides changing cohorts.
    for _ in range(customer_count):
        signup_offset = rng.randint(0, 89) if rng.random() < 0.65 else rng.randint(90, (END - START).days - 25)
        signup = START + timedelta(days=signup_offset)
        region_id = rng.randint(1, 4)
        segment = rng.choices(("startup", "sme", "enterprise"), (30, 50, 20))[0]
        customer = add("customers", company_name=f"Demo Company {len(data['customers']) + 1:04d}",
            segment=segment, region_id=region_id, sales_rep_id=(region_id - 1) * 2 + rng.randint(1, 2),
            signup_date=signup, acquisition_channel=rng.choice(("organic", "paid_search", "partner", "referral")),
            status="active")
        customer_id = customer["customer_id"]
        if rng.random() < 0.75:
            start = signup + timedelta(days=rng.randint(0, 14))
            end = None
            for month in months():
                if month <= start:
                    continue
                probability = 0.38 if segment == "enterprise" and month >= date(2026, 9, 1) else 0.012
                if rng.random() < probability:
                    end = month + timedelta(days=rng.randint(0, calendar.monthrange(month.year, month.month)[1] - 1))
                    break
            plan, value = {"startup": ("starter", 49), "sme": ("growth", 199), "enterprise": ("enterprise", 999)}[segment]
            sub = add("subscriptions", customer_id=customer_id, plan=plan, monthly_value=money(value),
                start_date=start, end_date=end, status="cancelled" if end else "active")
            if end:
                customer["status"] = "churned"
                ticket(customer_id, end - timedelta(days=1), "cancellation", "high")
            for month in months():
                bill_day = date(month.year, month.month, min(start.day, calendar.monthrange(month.year, month.month)[1]))
                if bill_day < start or (end and bill_day >= end):
                    continue
                add("payments", customer_id=customer_id, order_id=None, subscription_id=sub["subscription_id"],
                    payment_date=bill_day, amount=money(value),
                    payment_status="completed" if rng.random() < 0.98 else "failed")

        for month in months():
            if next_month(month) <= signup:
                continue
            chance = {"startup": 0.40, "sme": 0.60, "enterprise": 0.80}[segment]
            if region_id == 1 and month >= date(2026, 7, 1):
                chance *= 0.18
            if rng.random() >= chance:
                continue
            first = max(month, signup)
            order_day = first + timedelta(days=rng.randrange((next_month(month) - first).days))
            status = rng.choices(("completed", "cancelled", "pending"), (92, 6, 2))[0]
            if status == "pending" and month < date(2026, 9, 1):
                status = "cancelled"
            chosen = rng.sample(data["products"], rng.choices((1, 2, 3), (65, 25, 10))[0])
            items = [(product, rng.randint(1, 3), money(product["price"] * rng.choice((Decimal("1"), Decimal("0.9")))))
                     for product in chosen]
            total = sum((product_price * quantity for _, quantity, product_price in items), Decimal("0"))
            order = add("orders", customer_id=customer_id, order_date=order_day, status=status,
                total_amount=total, region_id=region_id)
            for product, quantity, product_price in items:
                add("order_items", order_id=order["order_id"], product_id=product["product_id"],
                    quantity=quantity, unit_price=product_price)
            if status == "pending":
                continue
            payment = add("payments", customer_id=customer_id, order_id=order["order_id"], subscription_id=None,
                payment_date=order_day, amount=total, payment_status="completed" if status == "completed" else "failed")
            defect = order_day >= date(2026, 8, 1) and any(p["product_id"] == 3 for p in chosen)
            refund_day = order_day + timedelta(days=rng.randint(2, 10))
            if status == "completed" and refund_day < END and rng.random() < (0.42 if defect else 0.025):
                add("refunds", payment_id=payment["payment_id"], refund_date=refund_day,
                    amount=money(total * rng.choice((Decimal("0.25"), Decimal("0.5"), Decimal("1")))),
                    reason="product_defect" if defect else rng.choice(("not_needed", "service_issue")))
                ticket(customer_id, refund_day - timedelta(days=1), "technical" if defect else "billing", "high" if defect else "medium")
        if rng.random() < 0.3:
            ticket(customer_id, signup + timedelta(days=2), "onboarding", "low")

    return data, manifest_for(data, seed)


def write_dataset(data, manifest, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for table, rows in data.items():
        (output / f"{table}.csv").write_bytes(csv_text(table, rows).encode("utf-8"))
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customers", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "seed")
    args = parser.parse_args()
    data, manifest = generate_dataset(args.customers, args.seed)
    write_dataset(data, manifest, args.output)
    print(json.dumps({"output": str(args.output), "rows": manifest["row_counts"], "content_hash": manifest["content_hash"]}, indent=2))


if __name__ == "__main__":
    main()
