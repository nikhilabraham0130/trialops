"""Fail-closed AST policy for a deliberately narrow clinical SELECT subset."""

from enum import StrEnum
from typing import Never

from sqlglot import exp, parse
from sqlglot.errors import ParseError

MAX_QUERY_LENGTH = 4000
MAX_ROWS = 100

APPROVED_COLUMNS: dict[str, frozenset[str]] = {
    "vw_subjects": frozenset(
        {
            "dataset_version_id",
            "unique_subject_id",
            "age",
            "sex",
            "actual_arm",
        }
    ),
    "vw_adverse_events": frozenset(
        {
            "dataset_version_id",
            "unique_subject_id",
            "event_sequence",
            "preferred_term",
            "severity",
            "serious_flag",
            "start_date_text",
        }
    ),
    "vw_laboratory_results": frozenset(
        {
            "dataset_version_id",
            "unique_subject_id",
            "result_sequence",
            "test_code",
            "standard_result",
            "standard_unit",
            "lower_reference_limit",
            "upper_reference_limit",
            "range_indicator",
            "baseline_flag",
            "observed_at_text",
        }
    ),
}

ALLOWED_NODES: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.From,
    exp.Table,
    exp.Column,
    exp.Identifier,
    exp.Star,
    exp.Literal,
    exp.Null,
    exp.Boolean,
    exp.Alias,
    exp.Distinct,
    exp.Where,
    exp.Group,
    exp.Having,
    exp.Order,
    exp.Ordered,
    exp.Limit,
    exp.Count,
    exp.Sum,
    exp.Avg,
    exp.Min,
    exp.Max,
    exp.EQ,
    exp.NEQ,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.And,
    exp.Or,
    exp.Not,
    exp.Is,
    exp.In,
    exp.Between,
    exp.Like,
    exp.ILike,
    exp.Paren,
    exp.Add,
    exp.Sub,
    exp.Mul,
    exp.Div,
    exp.Neg,
)


class SQLPolicyErrorCode(StrEnum):
    QUERY_TOO_LONG = "SQL_QUERY_TOO_LONG"
    PARSE_ERROR = "SQL_PARSE_ERROR"
    POLICY_VIOLATION = "SQL_POLICY_VIOLATION"


class SQLPolicyError(ValueError):
    def __init__(self, code: SQLPolicyErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _reject(message: str) -> Never:
    raise SQLPolicyError(SQLPolicyErrorCode.POLICY_VIOLATION, message)


def validate_clinical_sql(candidate_sql: str) -> str:
    """Parse, inspect, and normalize one simple SELECT over one curated view."""
    if not candidate_sql.strip():
        _reject("A SELECT query is required.")
    if len(candidate_sql) > MAX_QUERY_LENGTH:
        raise SQLPolicyError(
            SQLPolicyErrorCode.QUERY_TOO_LONG,
            "The SQL query exceeds the allowed length.",
        )
    try:
        statements = parse(candidate_sql, read="postgres")
    except ParseError as exc:
        raise SQLPolicyError(
            SQLPolicyErrorCode.PARSE_ERROR,
            "The SQL query could not be parsed as PostgreSQL syntax.",
        ) from exc
    if len(statements) != 1:
        _reject("Only one SELECT statement is permitted.")
    query = statements[0]
    if not isinstance(query, exp.Select):
        _reject("Only one SELECT statement is permitted.")

    for node in query.walk():
        if not isinstance(node, ALLOWED_NODES):
            _reject(f"The query uses a disallowed SQL construct: {type(node).__name__}.")

    tables = list(query.find_all(exp.Table))
    if len(tables) != 1:
        _reject("Exactly one curated clinical view must be queried.")
    table = tables[0]
    if table.db or table.catalog or table.name not in APPROVED_COLUMNS:
        _reject("The query references a relation outside the approved clinical views.")
    if table.alias:
        _reject("Table aliases are not supported in the initial SQL policy.")

    allowed_columns = APPROVED_COLUMNS[table.name]
    aliases = {item.alias for item in query.expressions if item.alias}
    for column in query.find_all(exp.Column):
        if column.table or column.db or column.catalog:
            _reject("Qualified column references are not supported in the initial SQL policy.")
        if column.name not in allowed_columns and column.name not in aliases:
            _reject("The query references a column outside the approved view.")

    output_names = [item.output_name for item in query.expressions]
    if not output_names or any(not name for name in output_names):
        _reject("Every selected expression must have a visible column name or alias.")
    if len(set(output_names)) != len(output_names):
        _reject("Selected columns must have distinct output names.")

    limit = query.args.get("limit")
    if limit is not None:
        limit_value = limit.expression
        if not isinstance(limit_value, exp.Literal) or not limit_value.is_int:
            _reject("LIMIT must be a positive integer no greater than 100.")
        if not 1 <= int(limit_value.this) <= MAX_ROWS:
            _reject("LIMIT must be a positive integer no greater than 100.")
    else:
        query = query.limit(MAX_ROWS)
    return query.sql(dialect="postgres")
