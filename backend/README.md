# TrialOps API

This directory contains the TrialOps FastAPI backend.

## Local setup

From the repository root, activate the existing virtual environment and install
the backend with its development tools:

```powershell
Copy-Item .env.example .env
& ".\.venv\Scripts\Activate.ps1"
python -m pip install --editable ".\backend[dev]"
```

`--editable` means Python imports the package from this source directory. Code
changes are therefore available without reinstalling the package. The install
also includes SQLAlchemy, which manages database connections and transactions,
and Psycopg, which is the PostgreSQL driver SQLAlchemy uses to communicate with
the database server.

## Local PostgreSQL

Start the PostgreSQL container from the repository root:

```powershell
docker compose up --detach postgres
docker compose ps
```

Docker Compose reads the ignored `.env` file and creates the configured database
and user. The health status becomes `healthy` when PostgreSQL is ready to accept
connections. A named Docker volume preserves its database files when the
container stops or is recreated.

Confirm that PostgreSQL can execute a query:

```powershell
docker compose exec postgres psql --username trialops --dbname trialops --command "SELECT 1;"
```

Apply every pending database migration from the `backend` directory:

```powershell
cd backend
python -m alembic upgrade head
python -m alembic current
```

Alembic records the applied revision in PostgreSQL's `alembic_version` table.
Each migration is an ordered schema change, allowing a new or existing TrialOps
database to reach the same table structure without manual SQL.

Stop the local database without deleting its stored data:

```powershell
docker compose down
```

## Run the API

```powershell
cd backend
python -m uvicorn trialops.main:app --reload --env-file ..\.env
```

The API will be available at `http://127.0.0.1:8000`. FastAPI's interactive API
documentation will be available at `http://127.0.0.1:8000/docs`.

## Health checks

- `GET /health/live` confirms that the API process is running.
- `GET /health/ready` confirms that the application has valid configuration and
  is ready to receive requests. A database-connectivity readiness check is still
  deferred.

## Study catalog

`GET /studies` returns every registered study and each of its dataset versions,
including the normalized DM subject count for that exact version. The endpoint
does not silently choose a "latest" version because callers must know which
immutable data snapshot produced a count.

Example response:

```json
{
  "studies": [
    {
      "id": "e0673be2-39ad-4b26-b6fb-4f322e8cd553",
      "study_oid": "CDISCPILOT01",
      "title": null,
      "dataset_versions": [
        {
          "id": "84e8aba3-f839-4e00-8d77-93e8c9752f17",
          "version_label": "cdisc-pilot-667511d4",
          "status": "RECEIVED",
          "subject_count": 306
        }
      ]
    }
  ]
}
```

## Adverse-event parsing foundation

`trialops.datasets.adverse_events.parse_adverse_events` turns an AE Dataset-JSON
document into typed event records. It uses the file's column metadata rather than
fixed row positions, preserves the source row number, and requires a unique
`USUBJID` + `AESEQ` pair for each event. It also keeps `AESEV` (intensity) separate
from `AESER` (seriousness). A blank `AEENDTC` becomes `None`.

`store_adverse_events` saves a parsed batch in one transaction. An AE event can
only reference a DM subject with the same dataset version, and PostgreSQL
enforces that relationship with a composite foreign key. The storage function
also rejects repeated imports and missing subjects before inserting any rows.

The local demo import verified and stored 1,191 AE rows alongside 306 DM
subjects. These are raw event records, not a validated safety analysis. A
dataset remains in `RECEIVED` status until the validation workflow is built.
Date strings are preserved for later clinical date validation; treatment
emergence and subject-level incidence are not calculated by this importer.

## Laboratory-result parsing foundation

`trialops.datasets.laboratory_results.parse_laboratory_results` converts LB
Dataset-JSON rows into typed laboratory results using the file's column names.
It retains each source row number and the `USUBJID` + `LBSEQ` result identity.
Missing numeric results, units, reference limits, range indicators, and baseline
flags become `None`; a numeric zero remains zero. Numeric values use `Decimal`
so the importer does not introduce binary floating-point rounding.

The public pilot LB file contains 59,580 rows. This parser does **not** yet store
them in PostgreSQL, validate clinical reference ranges or timing, or calculate
ALT abnormalities. Those steps need their own tested rules.

## Configuration

The API reads `TRIALOPS_`-prefixed environment variables. Uvicorn's `--env-file`
option loads the repository's ignored `.env` file into the process before the
application starts.

| Variable | Allowed values | Default |
| --- | --- | --- |
| `TRIALOPS_ENV` | `development`, `test`, `production` | `development` |
| `TRIALOPS_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |
| `TRIALOPS_POSTGRES_USER` | Local PostgreSQL username | `trialops` |
| `TRIALOPS_POSTGRES_PASSWORD` | Local PostgreSQL password | none |
| `TRIALOPS_POSTGRES_DB` | Local PostgreSQL database name | `trialops` |
| `TRIALOPS_POSTGRES_PORT` | Host port published by Docker | `55432` |
| `TRIALOPS_DATABASE_URL` | SQLAlchemy URL using `postgresql+psycopg` | local PostgreSQL |

An unsupported value causes application startup to fail rather than silently
using an unintended configuration.

Database URLs have the shape
`postgresql+psycopg://username:password@host:port/database`. TrialOps keeps this
value wrapped as a secret so accidental settings output does not reveal the
password. The committed `.env.example` contains development-only placeholder
credentials; real credentials belong only in the ignored `.env` file.
The username, password, database name, and port in `TRIALOPS_DATABASE_URL` must
match the corresponding local PostgreSQL values.

## Local quality checks

Run these commands from the `backend` directory:

```powershell
python -m ruff check src tests migrations
python -m ruff format --check src tests migrations
python -m mypy
python -m pytest --cov=trialops
```
