# TrialOps data directories

TrialOps separates data provenance records from participant-level source data.

- `manifests/` contains reviewable source identities, expected file sizes, and
  SHA-256 checksums. Manifests contain no participant records and are committed.
- `raw/` is reserved for byte-for-byte source artifacts and is ignored by Git.
- `processed/` is reserved for generated normalized data and is ignored by Git.

Never commit restricted or participant-level data. Public source artifacts must
also be reviewed against their terms before distribution. The CDISC pilot files
are acquired separately and must remain unchanged.
