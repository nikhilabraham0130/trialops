# TrialOps frontend

This React and TypeScript application provides an analysis workspace above the
study catalog. Select a dataset version, ask an ALT safety question, review the
AI-proposed approved tool, and explicitly confirm before Python runs the
calculation. The structured result and source evidence are shown separately
from the AI interpretation. A saved plan ID is placed in the page URL so a
refresh reloads its state from PostgreSQL.

The existing direct `Run ALT check` action remains available in the study
catalog. Both paths request the backend's versioned `ALT > 3x ULN` calculation.

The browser displays the returned method version, eligible measurements,
qualifying measurements, distinct-subject count, timing limitation, validation
findings, and source evidence. It does not repeat the clinical calculation in
TypeScript. Keeping that calculation in the backend gives every client the same
tested result and prevents presentation code from becoming a second source of
statistical truth.

The workspace calls `POST /agent/plans`, `POST /agent/plans/{id}/confirm`,
`POST /agent/plans/{id}/interpretation`, and `GET /agent/plans/{id}`. Planning
and explanation require a configured AI provider; calculation and saved plan
retrieval use the stored backend state. If the provider is unavailable, the page
shows the backend error and leaves any completed calculation visible.

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
