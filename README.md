# TrialOps AI

TrialOps AI is a governed clinical-trial analytics platform designed to make
AI-assisted analyses traceable, reviewable, and reproducible.

## The problem

Clinical-trial analyses are often spread across SQL, Python, R, SAS, and manual
review workflows. Natural-language interfaces can make analysis more accessible,
but regulated work requires more than a plausible answer: important results must
be calculated deterministically, grounded in evidence, tied to an exact dataset
version, and reviewed when required.

TrialOps explores how an AI assistant can orchestrate trusted analytical tools
without becoming the source of statistical truth.

## Core design principle

> AI decides which approved capability to use. Trusted software performs the
> important calculation.

The language model may interpret a question, select a controlled tool, or
generate a candidate read-only query. Deterministic application code calculates
statistics and the platform records the evidence, versions, and review history.

## Initial scope

The first complete workflow will support one clinical study and three
SDTM-inspired domains:

- `DM`: demographics and treatment assignment
- `AE`: adverse events
- `LB`: laboratory results

The initial analytical workflows will cover:

- Severe adverse-event incidence by treatment arm
- Laboratory abnormality analysis
- Subject-level safety summaries

The product will add dataset validation and versioning, governed text-to-SQL, a
tool-using analysis agent, evidence grounding, human review, audit history,
lineage, and deterministic reproduction.

## Data approach

The project will begin with public CDISC pilot/reference data used according to
its applicable terms and with clear attribution. Restricted participant-level
data will never be committed to this repository. Independent synthetic fixtures
may be created for invalid-data scenarios, edge cases, and operational testing.

## Planned technology

- React and TypeScript frontend
- Python and FastAPI backend
- PostgreSQL persistence
- Pandas, SciPy, and statsmodels analytics
- Docker Compose for local deployment

Specific libraries will be added only when the product requires them.

## Project status

TrialOps is in the initial foundation and product-design phase. Setup and usage
instructions will be added as executable components are introduced.

## Important disclaimer

TrialOps is an educational portfolio project. It is not a validated clinical
system, medical device, or source of medical advice, and it must not be used for
real clinical or regulatory decisions.
