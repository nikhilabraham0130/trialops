# TrialOps frontend

This React and TypeScript application displays the studies and normalized DM
subject counts supplied by the FastAPI backend. Each dataset version also has a
`Run ALT check` action that requests the backend's versioned `ALT > 3x ULN`
calculation.

The browser displays the returned method version, eligible measurements,
qualifying measurements, distinct-subject count, timing limitation, validation
findings, and source evidence. It does not repeat the clinical calculation in
TypeScript. Keeping that calculation in the backend gives every client the same
tested result and prevents presentation code from becoming a second source of
statistical truth.

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
