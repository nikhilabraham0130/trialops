"""Candidate SQL must be a narrow, single-view, bounded SELECT."""

import pytest

from trialops.sql.policy import MAX_ROWS, SQLPolicyError, SQLPolicyErrorCode, validate_clinical_sql


def test_normalizes_a_grouped_query_and_adds_row_limit() -> None:
    validated = validate_clinical_sql(
        "SELECT actual_arm, COUNT(*) AS subject_count FROM vw_subjects "
        "GROUP BY actual_arm ORDER BY subject_count DESC"
    )
    assert validated.endswith(f"LIMIT {MAX_ROWS}")
    assert "vw_subjects" in validated


def test_preserves_a_smaller_explicit_limit() -> None:
    assert validate_clinical_sql("SELECT unique_subject_id FROM vw_subjects LIMIT 5").endswith(
        "LIMIT 5"
    )


@pytest.mark.parametrize(
    "candidate",
    [
        "SELECT * FROM vw_subjects; DROP TABLE dm_subject",
        "DELETE FROM vw_subjects",
        "SELECT * FROM agent_plan",
        "SELECT * FROM dm_subject",
        "SELECT * FROM pg_catalog.pg_roles",
        "SELECT * FROM vw_subjects JOIN vw_adverse_events USING (unique_subject_id)",
        "WITH x AS (SELECT * FROM vw_subjects) SELECT * FROM x",
        "SELECT * FROM vw_subjects UNION SELECT * FROM vw_subjects",
        "SELECT pg_sleep(1) AS paused FROM vw_subjects",
        "SELECT set_config('trialops.dataset_version_id', 'other', true) "
        "AS changed FROM vw_subjects",
        "SELECT * FROM vw_subjects FOR UPDATE",
        "SELECT secret FROM vw_subjects",
        "SELECT * FROM vw_subjects LIMIT 101",
        "SELECT * FROM vw_subjects LIMIT 0",
        "SELECT COUNT(*) FROM vw_subjects",
        "SELECT * FROM vw_subjects OFFSET 10000",
    ],
)
def test_rejects_queries_outside_the_initial_policy(candidate: str) -> None:
    with pytest.raises(SQLPolicyError) as raised:
        validate_clinical_sql(candidate)
    assert raised.value.code is SQLPolicyErrorCode.POLICY_VIOLATION


def test_rejects_query_above_length_limit() -> None:
    with pytest.raises(SQLPolicyError) as raised:
        validate_clinical_sql("SELECT * FROM vw_subjects " + " " * 4000)
    assert raised.value.code is SQLPolicyErrorCode.QUERY_TOO_LONG


def test_rejects_invalid_postgres_syntax_without_leaking_parser_details() -> None:
    with pytest.raises(SQLPolicyError) as raised:
        validate_clinical_sql("SELECT FROM vw_subjects WHERE (")
    assert raised.value.code is SQLPolicyErrorCode.PARSE_ERROR
    assert "could not be parsed" in str(raised.value)
