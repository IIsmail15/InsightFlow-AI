# InsightFlow AI — Milestone 1

InsightFlow's eventual goal is to help business users investigate company data in plain English. This milestone supplies the evidence: a PostgreSQL database, repeatable synthetic records, and five precisely defined SQL metrics. The working interface is SQL. Frontend, API, LLM integration, and Azure belong to later milestones.

The demonstration company sells software subscriptions and one-off implementation, training, consulting, and add-on products in four UK regions. All amounts are GBP, excluding tax. The observation window is **1 January 2025 through 30 September 2026**. Dates are deliberately fixed so demonstrations and exercises remain reproducible.

## Run locally with Docker

Install Docker Desktop with Linux containers and wait until its engine is running. A host Python installation is unnecessary for this route. Run these commands from the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
docker compose up -d --wait db
docker compose run --rm --build seed
docker compose run --rm seed python scripts/verify_database.py --assert-events
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Copy `.env` only on first setup; preserve your existing configuration on later runs. The first seed run creates the tables and views and loads all records in one transaction. Running it again with identical input verifies integrity and inserts nothing. PostgreSQL data persists in a named Docker volume.

This workstation's ignored `.env` uses **`POSTGRES_PORT=55433`** because port 5432 is unavailable. The database is reachable at `localhost:55433`; connections inside Docker still use `db:5432`. Fresh clones retain the example's default port 5432 unless you change it.

At the `psql` prompt:

```sql
\dt
\dv analytics.*
SELECT * FROM analytics.monthly_revenue ORDER BY month_start;
SELECT * FROM analytics.monthly_mrr ORDER BY month_start;
SELECT * FROM analytics.monthly_average_order_value ORDER BY month_start;
SELECT * FROM analytics.monthly_refund_rate ORDER BY month_start;
SELECT * FROM analytics.monthly_customer_churn ORDER BY month_start;
\q
```

`docker compose stop` pauses the services and keeps data. `docker compose down` removes the containers and keeps the named volume. Adding `--volumes` to `down` deletes the database; use it only when you intend to discard the local demo.

## Dataset and initial metrics

The default seed is `42`, with 1,200 customers, 10,905 orders, 15,753 order items, 886 subscriptions, 23,867 payment attempts, 363 refunds, and 916 support tickets. It also includes four regions, eight sales representatives, and six products.

| Metric view in `analytics` | Definition |
| --- | --- |
| `monthly_revenue` | Completed payment amounts, including subscriptions, grouped by payment date; gross of refunds. |
| `monthly_mrr` | Monthly contract value active on the month's final day. |
| `monthly_average_order_value` | Completed one-off order totals divided by completed order count. |
| `monthly_refund_rate` | Refund amounts issued during the month divided by gross completed payments collected that month. |
| `monthly_customer_churn` | Opening subscribers who cancel during the month divided by opening subscribers. |

Rates are fractions: `0.05` means 5%. A zero denominator produces `NULL`. Revenue and MRR produce zero for empty periods. The churn opening cohort includes customers active immediately before the first day; first-day cancellations count in that month. Same-month signups are excluded from this cohort. Subscription `end_date` is the first inactive day.

Three events are intentionally embedded:

- **July 2026:** North-region order frequency declines; subscription income cushions the impact on total regional revenue.
- **August 2026:** orders containing Analytics Export receive more refunds, with accompanying technical support tickets.
- **September 2026:** enterprise subscription cancellations increase, with cancellation tickets.

The generator records the injection rules in `data/seed/manifest.json` when exporting CSVs. `database/event_evidence.sql` contains verification queries. The measured signals provide evidence of changes; the fictional injection rules are known ground truth, not a claim that SQL correlations establish real-world causes.

Measured from PostgreSQL using the default dataset:

| Signal | Baseline | Event period |
| --- | --- | --- |
| North gross revenue | Apr–Jun 2026: GBP 1,097,108 | Jul–Sep 2026: GBP 339,588 (**−69.05%**) |
| Refund amount rate | Jun–Jul 2026: 1.34% | Aug–Sep 2026: **4.19%** |
| Enterprise customer churn | August 2026: 2.76% | September 2026: **36.99%** |

## Generate inspectable CSVs

The generator needs only Python 3.12's standard library:

```powershell
python scripts/generate_data.py
```

This writes ten CSVs and a manifest containing row counts, SHA-256 checksums, observation dates, and event assumptions into ignored `data/seed/`. Regeneration overwrites those generated files. To choose another output and random seed:

```powershell
python scripts/generate_data.py --customers 2000 --seed 7 --output data/seed/alternative
```

Very small datasets are useful for inspection but may not show statistically clear events. The event acceptance thresholds are verified for the default 1,200 customers and seed 42.

To load the exported default CSVs using Docker:

```powershell
docker compose run --rm -v "${PWD}/data/seed:/seed:ro" seed python scripts/seed_database.py --data-dir /seed
```

Without `--data-dir`, seeding generates the default data in memory. It does not depend on a previous CSV export. A different dataset is refused unless you explicitly request replacement:

```powershell
docker compose run --rm seed python scripts/seed_database.py --customers 2000 --seed 7 --replace
```

`--replace` replaces the known demo tables transactionally and preserves the schema. It does not use `CASCADE`. If loading or integrity validation fails, the previous dataset survives.

## Optional local Python connection

Keep PostgreSQL in Docker and run the scripts on your host:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
$env:PGHOST = "localhost"
$env:PGPORT = "5432"
$env:PGDATABASE = "insightflow"
$env:PGUSER = "insightflow"
$env:PGPASSWORD = "insightflow_local_only"
.\.venv\Scripts\python.exe scripts/seed_database.py --data-dir data/seed
.\.venv\Scripts\python.exe scripts/verify_database.py --assert-events
```

Match these variables to your `.env` values. Compose reads `.env`; the Python scripts use standard PostgreSQL environment variables or an optional `DATABASE_URL`. They do not automatically parse `.env`. Psycopg is the only direct dependency; SQLAlchemy and Pandas are unnecessary for this milestone's explicit SQL and CSV loading.

## Tests

Generator and metadata tests, without Docker or installed dependencies:

```powershell
python -m unittest discover -s backend/tests -p test_generator.py -v
```

All tests against the running, seeded PostgreSQL database:

```powershell
docker compose run --rm -e RUN_DATABASE_TESTS=1 seed python -m unittest discover -s backend/tests -v
```

Integration tests replace rows inside a transaction and roll back after every test. Run them against this local demo database without concurrent queries. They verify hand-calculated money totals, failed-payment exclusion, multi-item join safety, zero denominators, cross-month refunds, month-boundary cancellations, foreign keys, and cross-table integrity checks. Without `RUN_DATABASE_TESTS=1`, database tests are explicitly skipped.

The verification script additionally checks generated records and asserts the three planted events using PostgreSQL queries. It runs in a read-only transaction.

Validation on 5 October 2026: **all 14 tests passed inside the Python container against PostgreSQL 17 in Docker**, including all nine database/loader tests. The seed loaded 53,908 business records, repeat seeding inserted no duplicates, an invalid replacement rolled back, and SQL verified all three event thresholds. Generated CSV checksums, Python syntax, and Compose configuration also validated. The same suite passed against a temporary PostgreSQL 18 cluster, which was removed after testing.

This machine's initial full-disk condition damaged downloaded image layers; those task-specific layers were replaced after space was freed. Its network also required a trusted CA bundle for the Python dependency download. The resulting seed image and database are ready to use.

## Files and design

Read [the major-file walkthrough and data model](docs/data-foundation.md), then attempt [three SQL exercises](docs/exercises.md). Official metric definitions live in [metrics.json](backend/app/metadata/metrics.json). A future backend can read this metadata; the current executable source of metric calculations is [metrics.sql](database/metrics.sql).

Schema version 1 is recorded with a checksum in `schema_migrations`. Modifying an already-applied `schema.sql` is refused, even with `--replace`. Future schema changes need explicit migrations; a disposable development database can instead be recreated. View definitions are reapplied on each seed run. Avoid concurrent seed runs; an advisory transaction lock also prevents accidental overlap.

## Likely failure modes

- **Docker pipe/daemon connection error:** open Docker Desktop and wait for the Linux engine. `docker info` must work before Compose can create PostgreSQL.
- **Docker storage I/O errors or no disk space:** free host disk space before restarting Docker Desktop and retrying downloads. Preserve existing database volumes; a factory reset is not part of this project's setup.
- **Certificate verification failure during `pip install` in Docker:** use the optional trusted CA build secret described below. Host certificate trust is not automatically inherited by a Linux image.
- **Port 5432 already occupied:** set `POSTGRES_PORT=5433` in `.env` and recreate the database container. Local Python then uses `PGPORT=5433`; containers still use port 5432.
- **Authentication failure after editing `.env`:** PostgreSQL initialization credentials apply only when the volume is first created. Restore the original credentials or deliberately create a fresh demo volume.
- **Checksum mismatch:** CSVs have changed since generation. Regenerate them together with the manifest. Use SQL in a rollback transaction for experiments instead of modifying checked CSVs.
- **Different dataset / changed schema:** use `--replace` for intentional data replacement. It does not override migration checksums.
- **Unexpected metric values:** use the fixed observation dates rather than `CURRENT_DATE`, check statuses and date boundaries, and aggregate different fact tables before joining them. Averaging monthly rates does not give a correctly weighted multi-month rate.

The database binds only to `127.0.0.1`. Its example credentials and owner role are for local development. The seed script uses fixed SQL, allowlisted table identifiers, and bound values. No model-generated SQL is executed in this milestone. A later query interface must use a read-only role, parsed SELECT-only validation, table/schema allowlists, timeouts, and result limits; the current owner credentials must not be reused for that interface.

## Optional build certificate bundle

On networks with a private certificate authority, put an approved PEM CA bundle at `.local-build/ca.pem`. This directory is ignored by Git and excluded from the Docker build context. A bundle exported from this workstation's Windows trust stores is already present locally. Build using:

```powershell
docker build --secret id=pip_ca,src=.local-build/ca.pem -t insightflow-ai-seed:latest .
docker compose run --rm seed
```

The tag above matches Compose's default image name when the checkout is named `InsightFlow-AI`. If using a different Compose project name, adjust the tag to `<project-name>-seed:latest`. The optional BuildKit secret is available only during dependency installation and is not baked into the image. TLS certificate verification stays enabled. Ordinary networks do not need this secret.
