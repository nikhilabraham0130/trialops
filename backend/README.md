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
  is ready to receive requests. Database readiness will be added when PostgreSQL
  is introduced.

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
| `TRIALOPS_POSTGRES_PORT` | Host port published by Docker | `5432` |
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
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy
python -m pytest --cov=trialops
```
