# CDISC Pilot Data Source Assessment

| Field | Value |
| --- | --- |
| Decision | Accepted for the initial public demo |
| Assessment date | 2026-09-10 |
| Source | CDISC SDTM/ADaM Pilot Project |
| Source repository | https://github.com/cdisc-org/sdtm-adam-pilot-project |
| Inspected revision | `667511d4b183871d74392ba691c935c38d431d39` |
| Study identifier | `CDISCPILOT01` |
| Dataset-JSON version | 1.1.0 |
| SDTM metadata version | SDTMIG 3.1.2 |

## 1. Purpose

TrialOps needs a public clinical reference dataset that supports realistic
cross-domain safety analysis and can be used in a reproducible portfolio demo.
This assessment checks whether the CDISC pilot package supports the initial DM,
AE, and LB workflows before application code is designed around it.

This document is a technical source assessment, not a legal opinion or a claim
that the data is suitable for clinical decision-making.

## 2. Source characterization

The source repository describes the package as clinical test data made available
for public information and research discussion. It includes SDTM and ADaM data,
`define.xml` metadata, study documentation, and both XPT and Dataset-JSON
representations.

TrialOps will describe it as **public CDISC pilot/reference data**. The project
will not claim that it is a real de-identified trial, synthetic data, or a
currently conformant regulatory submission unless the source documentation
explicitly supports that claim.

## 3. Domain inventory

| Domain | Records | Distinct subjects | Columns | MVP suitability |
| --- | ---: | ---: | ---: | --- |
| DM | 306 | 306 | 25 | Suitable |
| AE | 1,191 | 225 | 35 | Suitable |
| LB | 59,580 | 254 | 23 | Suitable |

DM contains the subject identifier, planned and actual treatment arms,
demographics, and treatment start and end dates needed for population and
temporal definitions.

AE contains coded event terms, severity, seriousness, relationship, actions,
outcomes, and event dates needed for adverse-event summaries.

LB contains standardized test codes, numeric results, units, lower and upper
reference limits, normal-range indicators, baseline flags, visits, and dates
needed for laboratory-abnormality analysis.

## 4. Treatment populations

The source DM domain contains:

| Planned arm | Subjects |
| --- | ---: |
| Placebo | 86 |
| Xanomeline High Dose | 84 |
| Xanomeline Low Dose | 84 |
| Screen Failure | 52 |

The analytical population must exclude screen failures unless a workflow
explicitly asks about screening. TrialOps should support selecting two or more
actual source arms rather than relabeling the data as generic Treatment A and
Treatment B.

## 5. Workflow feasibility

### 5.1 Severe adverse-event comparison

The AE domain contains 43 records whose `AESEV` value is `SEVERE`. A preliminary
subject-level count found severe events in all three treated populations:

| Planned arm | Subjects with a severe AE | DM denominator |
| --- | ---: | ---: |
| Placebo | 7 | 86 |
| Xanomeline High Dose | 8 | 84 |
| Xanomeline Low Dose | 16 | 84 |

These counts only confirm that the proposed workflow has usable records. They are
not validated analytical results. The final function must define treatment
emergence, population membership, missing dates, and denominator rules before
calculating or interpreting incidence.

The source uses severity categories (`MILD`, `MODERATE`, and `SEVERE`), not CTCAE
grades. The MVP must therefore say **severe adverse events**, not **Grade 3 or
higher adverse events**.

### 5.2 Laboratory-abnormality analysis

The LB domain includes the tests needed for the planned safety workflows:

| Test code | Records |
| --- | ---: |
| ALT | 1,814 |
| AST | 1,814 |
| BILI | 1,814 |
| CREAT | 1,828 |
| HGB | 1,809 |
| PLAT | 1,788 |

It also contains standardized numeric results and upper reference limits. A
preliminary check found subjects with ALT greater than three times the reported
upper limit of normal, confirming that this edge case is present. The production
analysis must still define baseline handling, post-baseline timing, units, and
missing reference ranges explicitly.

### 5.3 Subject safety summary

`USUBJID` is available in all three domains, so demographics, adverse events, and
laboratory records can be connected at the subject level. The summary must retain
the source record identifiers needed to trace displayed evidence back to its
origin.

## 6. Format decision

TrialOps will initially ingest the Dataset-JSON files because they contain both
column metadata and rows and can be read without proprietary software. The
original XPT files remain useful reference artifacts, but XPT ingestion is not
required for the first vertical workflow.

The following source files are candidates for the initial import package:

- `dm.json`
- `ae.json`
- `lb.json`
- `define.xml`

Any source files included with TrialOps must remain byte-for-byte unchanged.
Their SHA-256 checksums and source revision must be recorded.

## 7. Terms and provenance controls

The source terms state that the data is provided as-is. They prohibit misleading
users about its origin or capabilities, prohibit modification or alteration of
the source data, prohibit distribution for a fee, and require attribution to
CDISC when the data is distributed.

TrialOps will therefore:

- Preserve included source files without modification.
- Display and document attribution to CDISC.
- Keep source files separate from TrialOps-owned test fixtures.
- Never present normalized or derived records as original CDISC artifacts.
- Record the upstream repository URL, revision, retrieval date, and checksums.
- Review the complete source disclaimer before publishing a data package.

Independent invalid-data fixtures will be created from TrialOps-owned schemas and
values. They will not be made by editing and redistributing CDISC source records.

## 8. Limitations

- The dataset has 306 DM subjects rather than the originally imagined 1,000.
  This is sufficient for the portfolio workflow and avoids artificial scaling.
- The study has three treated analysis arms plus screen failures rather than two
  generic treatment arms.
- AE severity is categorical and is not a CTCAE grade.
- Treatment-emergent status is not directly present in SDTM AE and must be
  derived from explicit date and exposure rules or obtained from an appropriate
  analysis dataset.
- Public reference data cannot establish that TrialOps is clinically valid.
- The source terms require care when packaging or deriving distributable
  artifacts.

## 9. Decision

The CDISC pilot package is technically suitable for the initial TrialOps demo.
It provides enough subjects, events, laboratory observations, metadata, and edge
cases to exercise the three planned analytical workflows.

The next data step is to define a source manifest and import contract. No source
data will be added to the TrialOps repository until attribution, checksums, and
the separation between original and derived artifacts are implemented.
