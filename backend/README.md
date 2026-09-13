# TrialOps API

This directory contains the TrialOps FastAPI backend.

## Local setup

From the repository root, activate the existing virtual environment and install
the backend with its development tools:

```powershell
& ".\.venv\Scripts\Activate.ps1"
python -m pip install --editable ".\backend[dev]"
```

`--editable` means Python imports the package from this source directory. Code
changes are therefore available without reinstalling the package.

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

An unsupported value causes application startup to fail rather than silently
using an unintended configuration.

## Local quality checks

Run these commands from the `backend` directory:

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy
python -m pytest --cov=trialops
```
