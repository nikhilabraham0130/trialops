# TrialOps AI Product Requirements

| Field | Value |
| --- | --- |
| Status | Draft |
| Version | 0.1 |
| Last updated | 2026-09-10 |
| Product type | Educational enterprise portfolio project |

## 1. Problem statement

Clinical-trial analysts often work across SQL, SAS, R, Python, spreadsheets, and
manual review processes. These tools can produce reliable analyses, but routine
questions may require specialized technical support and disconnected workflows.

Natural-language interfaces could make analysis more accessible, but a plausible
AI response is not sufficient in a regulated environment. Important results must
be calculated using trusted methods, tied to exact input data, supported by
evidence, reviewable by an authorized person, and reproducible later.

## 2. Product objective

TrialOps AI will allow a clinical analyst to ask a safety-related question in
natural language and receive a result produced by controlled analytical tools.
The platform will preserve the evidence, dataset version, method, agent actions,
governance decisions, and human-review history associated with that result.

TrialOps is intended to demonstrate how AI can assist with regulated analytics
without making the language model the source of statistical truth.

## 3. Core design principle

> AI selects and explains an approved capability. Deterministic software performs
> important calculations.

The system may use a language model to interpret a question, request
clarification, select a tool, or propose a read-only SQL query. Statistical
calculations and database operations must be performed by controlled application
components.

## 4. Initial users

### 4.1 Clinical analyst

The clinical analyst investigates study safety data. They need to:

- Select a study and an exact dataset version.
- Ask supported questions without writing SQL.
- Review the planned population, filters, and method before execution.
- Inspect results, evidence, SQL or analytical parameters, and agent actions.
- Save a draft and submit an analysis for review.

The analyst must not approve their own analysis when independent review is
required.

### 4.2 Statistician

The statistician needs to inspect and reproduce analytical work. They need to:

- Review the analysis population and statistical method.
- Inspect exact parameters and structured outputs.
- Confirm the analytical implementation version.
- Rerun an analysis against its original dataset version.
- Compare the original and reproduced outputs.

### 4.3 Reviewer

The reviewer decides whether an analysis can become an approved artifact. They
need to:

- Inspect the result and its evidence.
- Review the method or generated SQL.
- Inspect governance checks, lineage, and the agent trace.
- Approve, reject, or request changes with a recorded reason.

## 5. Primary workflow

The MVP will support this complete workflow:

1. An authorized user loads a clinical dataset.
2. TrialOps validates the dataset and creates an immutable version.
3. An analyst selects the study and dataset version.
4. The analyst asks a safety question in natural language.
5. TrialOps clarifies the request when necessary.
6. TrialOps presents a structured analysis plan.
7. The analyst confirms the plan.
8. The agent selects an approved analytical or SQL tool.
9. Trusted application code executes the analysis.
10. The AI explains only the structured result returned by the tool.
11. Governance policies evaluate the analysis and its evidence.
12. The analyst submits the analysis for review.
13. A reviewer approves, rejects, or requests changes.
14. An authorized user can reproduce an approved analysis later.

## 6. MVP data scope

The initial product will support one study with three SDTM-inspired domains:

- `DM`: one record per subject containing demographics and treatment assignment.
- `AE`: zero or more adverse-event records per subject.
- `LB`: zero or more laboratory-result records per subject and visit.

The public CDISC pilot/reference data will provide the initial reproducible demo
dataset, subject to its terms and attribution requirements. Restricted data must
not be committed to the repository. Independent synthetic fixtures may be used
to test validation failures, drift, and edge cases.

## 7. MVP analytical scope

The first release will support three trusted analytical workflows:

1. Compare severe adverse-event incidence across treatment arms.
2. Identify and summarize clinically defined laboratory abnormalities.
3. Produce a subject-level safety summary using demographics, adverse events,
   and laboratory results.

Exploratory questions may use governed text-to-SQL when no statistical
calculation is required.

## 8. Functional requirements

### FR-001: Dataset validation

The system must validate required columns, identifiers, controlled values, dates,
duplicates, subject references, and laboratory reference ranges before allowing
analysis.

Critical failures must block the affected dataset version.

### FR-002: Dataset versioning

Every accepted data load must create an immutable dataset version with source
metadata and file checksums. An analysis must reference exactly one dataset
version.

### FR-003: Controlled analysis execution

Important calculations must be performed by versioned deterministic functions.
The language model must not calculate or invent numerical results.

### FR-004: Governed text-to-SQL

Generated SQL must be parsed and validated before execution. Only read-only
queries against approved clinical views may execute. Row and execution-time
limits must be enforced.

### FR-005: Evidence-grounded interpretation

Every numerical claim in an AI-generated interpretation must be supported by a
field in the structured tool result. The analysis must expose its supporting
counts, filters, parameters, and source version.

### FR-006: Agent trace

Every agent run must record its tool selections, tool inputs, tool outcomes,
clarification steps, model version, prompt version, timestamps, and failures.

### FR-007: Governance evaluation

The system must evaluate enforceable policies covering dataset validity, SQL
safety, evidence presence, version metadata, and human review. Failed mandatory
policies must block submission or approval as applicable.

### FR-008: Human review

An analysis must move through explicit states: `Draft`, `Pending Review`,
`Changes Requested`, `Approved`, or `Rejected`. Review decisions must identify
the reviewer, timestamp, decision, and reason.

### FR-009: Audit history

Important actions must create append-only audit events containing the actor,
action, affected entity, and timestamp.

### FR-010: Lineage and reproduction

An approved analysis must expose its contributing dataset, parameters, query or
function, prompt, model, governance decision, and reviewer. The system must be
able to rerun the deterministic portion and compare it with the original output.

## 9. Quality requirements

### QR-001: Correctness

Analytical functions must have automated tests with independently calculated
expected results, including boundary and missing-data cases.

### QR-002: Reproducibility

The same dataset version, function version, and parameters must produce the same
structured analytical output.

### QR-003: Security and privacy

Secrets and restricted participant-level data must remain outside version
control. Database access used for analytical queries must be read-only and
limited to approved views.

### QR-004: Explainability

The interface must make the analysis population, method, evidence, agent trace,
governance status, and lineage understandable to the intended user.

### QR-005: Maintainability

Backend and frontend components must use explicit types, small testable units,
consistent error handling, and documented boundaries.

## 10. Initial success criteria

The MVP is successful when:

- All three supported analytical workflows can be completed through the UI.
- A critical data-validation failure prevents analysis.
- Unsafe or unauthorized SQL cannot execute.
- Every displayed numerical claim is traceable to structured evidence.
- An analyst cannot approve their own review-required analysis.
- An approved deterministic analysis can be reproduced exactly.
- The evaluation suite measures tool selection, numerical correctness,
  grounding, refusal behavior, and latency across at least 30 questions.
- A new developer can run the documented local setup without manually editing
  source code.

## 11. Out of scope for the MVP

- Use with real patients or real clinical decisions
- Regulatory submission or formal validation
- Full CDISC SDTM conformance
- Every SDTM domain
- Autonomous medical recommendations
- Language-model training or fine-tuning
- Predictive safety-risk modeling
- MLflow and model-drift monitoring
- Multi-organization tenancy
- Cloud production deployment

These items may be reconsidered only after the primary workflow is complete and
verified.

## 12. Known risks and open decisions

- The CDISC pilot data must be inspected to confirm the required DM, AE, and LB
  fields and applicable reuse terms.
- De-identified external datasets may require registration or prohibit public
  redistribution.
- Statistical definitions must be explicit and must not imply clinical validity.
- Language-model behavior is nondeterministic even when the analytical tools are
  deterministic.
- The eventual model provider and operational cost limits remain undecided.
