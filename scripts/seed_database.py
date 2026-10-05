"""Apply schema and atomically seed PostgreSQL. Repeats with identical input are safe."""

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path

import psycopg
from psycopg import sql

try:
    from .generate_data import COLUMNS, ROOT, generate_dataset, csv_text
except ImportError:  # support `python scripts/seed_database.py`
    from generate_data import COLUMNS, ROOT, generate_dataset, csv_text


def read_dataset(directory):
    """Check CSV checksums and headers before connecting or modifying the database."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    expected_hash = manifest["content_hash"]
    unsigned = {key: value for key, value in manifest.items() if key != "content_hash"}
    if hashlib.sha256(json.dumps(unsigned, sort_keys=True).encode("utf-8")).hexdigest() != expected_hash:
        raise ValueError("Manifest content hash does not match")
    if manifest["currency"] != "GBP":
        raise ValueError("Only GBP is supported")
    payloads = {}
    for table, columns in COLUMNS.items():
        content = (directory / f"{table}.csv").read_bytes()
        if hashlib.sha256(content).hexdigest() != manifest["sha256"][table]:
            raise ValueError(f"Checksum mismatch: {table}.csv; regenerate the dataset")
        rows = csv.reader(io.StringIO(content.decode("utf-8")))
        if tuple(next(rows)) != columns:
            raise ValueError(f"Unexpected columns in {table}.csv")
        if sum(1 for _ in rows) != manifest["row_counts"][table]:
            raise ValueError(f"Unexpected row count in {table}.csv")
        payloads[table] = content
    return payloads, manifest


def verify_data(conn):
    failures = [(name, count) for name, count in conn.execute(
        (ROOT / "database" / "checks.sql").read_text(encoding="utf-8")) if count]
    if failures:
        raise ValueError(f"Data integrity checks failed: {failures}")


def seed_database(payloads, manifest, replace=False):
    # Empty DSN uses standard PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD variables.
    # DATABASE_URL is optional for local Python use; never print connection secrets.
    with psycopg.connect(os.environ.get("DATABASE_URL", ""), connect_timeout=10) as conn:
        conn.execute("SET LOCAL search_path TO public")
        conn.execute("SET LOCAL lock_timeout = '10s'")
        conn.execute("SET LOCAL statement_timeout = '120s'")
        conn.execute("SELECT pg_advisory_xact_lock(178401)")
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version integer PRIMARY KEY, checksum text NOT NULL,
            applied_at timestamptz NOT NULL DEFAULT now())""")
        schema = (ROOT / "database" / "schema.sql").read_text(encoding="utf-8")
        checksum = hashlib.sha256(schema.encode("utf-8")).hexdigest()
        previous = conn.execute("SELECT checksum FROM schema_migrations WHERE version = 1").fetchone()
        if previous is None:
            conn.execute(schema)
            conn.execute("INSERT INTO schema_migrations (version, checksum) VALUES (1, %s)", (checksum,))
        elif previous[0] != checksum:
            raise ValueError("Applied schema.sql has changed. Add a migration or use a fresh development database.")

        conn.execute((ROOT / "database" / "metrics.sql").read_text(encoding="utf-8"))
        existing = conn.execute("SELECT content_hash FROM dataset_metadata WHERE dataset_id = 1").fetchone()
        if existing and existing[0] == manifest["content_hash"] and not replace:
            for table, expected in manifest["row_counts"].items():
                if table not in COLUMNS:
                    raise ValueError("Unexpected table in manifest")
                actual = conn.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))).fetchone()[0]
                if actual != expected:
                    raise ValueError(f"Existing {table} count differs; use --replace to restore synthetic data")
            verify_data(conn)
            print("Identical dataset already loaded; integrity checks passed, no rows inserted.")
            return
        if existing and not replace:
            raise ValueError("A different dataset is loaded. Use --replace only to replace this demo dataset.")
        if existing:
            # All known tables are explicit; no CASCADE into unrelated objects.
            tables = [sql.Identifier(table) for table in (*COLUMNS, "dataset_metadata")]
            conn.execute(sql.SQL("TRUNCATE {}").format(sql.SQL(", ").join(tables)))
        else:
            for table in COLUMNS:
                if conn.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {})").format(sql.Identifier(table))).fetchone()[0]:
                    raise ValueError("Unmanaged rows found; seed into an empty development database")
        conn.execute("""INSERT INTO dataset_metadata
            (dataset_id, random_seed, observation_start, observation_end, currency, content_hash)
            VALUES (1, %s, %s, %s, %s, %s)""", (
                manifest["seed"], manifest["observation_start"], manifest["observation_end"],
                manifest["currency"], manifest["content_hash"]))
        for table, columns in COLUMNS.items():
            statement = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE)").format(
                sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)))
            with conn.cursor().copy(statement) as copy:
                copy.write(payloads[table])
        verify_data(conn)
        for table in COLUMNS:
            conn.execute(sql.SQL("ANALYZE {}").format(sql.Identifier(table)))
    print(f"Seed committed: {sum(manifest['row_counts'].values()):,} business records; integrity checks passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Load previously generated CSVs; otherwise generate in memory")
    parser.add_argument("--customers", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--replace", action="store_true", help="Atomically replace existing synthetic rows")
    args = parser.parse_args()
    try:
        if args.data_dir:
            payloads, manifest = read_dataset(args.data_dir)
        else:
            data, manifest = generate_dataset(args.customers, args.seed)
            payloads = {table: csv_text(table, rows).encode("utf-8") for table, rows in data.items()}
        seed_database(payloads, manifest, args.replace)
    except (ValueError, OSError, KeyError, psycopg.Error) as error:
        # Database errors can contain values, but we deliberately never include the DSN.
        parser.exit(1, f"Seed failed ({type(error).__name__}): {error}\n")


if __name__ == "__main__":
    main()
