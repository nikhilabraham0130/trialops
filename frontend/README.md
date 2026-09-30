# TrialOps frontend

This React and TypeScript application provides an analysis workspace above the
study catalog. Select a dataset version, ask about ALT elevation or recorded
severe AEs by treatment arm, review the
AI-proposed approved tool, and explicitly confirm before Python runs the
calculation. The structured result and source evidence are shown separately
from the AI interpretation. A saved plan ID is placed in the page URL so a
refresh reloads its state from PostgreSQL.

Direct `Run ALT check` and `Run severe-AE check` actions are also available in
the study catalog. The catalog also has a subject safety lookup by `USUBJID`.
It reads DM, AE, and LB from one dataset version and displays source-linked
events and labs flagged by the source. The AI workspace can now choose any of
these three approved deterministic tools. The subject summary does not infer
diagnoses or treatment emergence.

The browser displays the returned method version, eligible measurements,
qualifying measurements, distinct-subject count, timing limitation, validation
findings, and source evidence. It does not repeat the clinical calculation in
TypeScript. Keeping that calculation in the backend gives every client the same
tested result and prevents presentation code from becoming a second source of
statistical truth.

The workspace calls `POST /agent/plans`, `POST /agent/plans/{id}/confirm`,
`POST /agent/plans/{id}/interpretation`, `GET /agent/plans/{id}`, and the
read-only `GET /agent/plans/{id}/governance` checklist. After execution, the
Reproduce result action calls `POST /agent/plans/{id}/reproduce` and displays
an exact match or field-level differences without changing the saved analysis.
Recheck governance after
execution or interpretation because the saved state has changed. A decision of
`REVIEW_REQUIRED` does not mean approved; independent review is not implemented
in the demo yet. Planning and explanation require a configured AI provider;
calculation and saved plan
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
