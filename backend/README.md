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
python -m uvicorn trialops.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`. FastAPI's interactive API
documentation will be available at `http://127.0.0.1:8000/docs`.

## Local quality checks

Run these commands from the `backend` directory:

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy
python -m pytest --cov=trialops
```
