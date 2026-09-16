# TrialOps frontend

This React and TypeScript application displays the studies and normalized DM
subject counts supplied by the FastAPI backend.

## Run locally

Start PostgreSQL and FastAPI first. Then, from this directory:

```powershell
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The frontend calls FastAPI at
`http://127.0.0.1:8000` by default. Copy `.env.example` to `.env` only when a
different API address is required.

## Quality checks

```powershell
npm run typecheck
npm test
npm run test:coverage
npm run build
```
