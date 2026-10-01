"""A model may draft SQL, but policy validation and execution remain separate."""

import asyncio
from uuid import uuid4

import pytest

from trialops.sql.model import SQLModelError, SQLModelRequest
from trialops.sql.planning import SQLPlanningError, SQLPlanningErrorCode, propose_clinical_sql


class FakeSQLModel:
    def __init__(self, response: str | Exception) -> None:
        self.response = response
        self.requests: list[SQLModelRequest] = []

    async def generate_sql_json(self, request: SQLModelRequest) -> str:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_valid_proposal_is_bound_to_selected_version_but_not_executed() -> None:
    model = FakeSQLModel(
        '{"candidate_sql":"SELECT actual_arm, COUNT(*) AS subjects FROM vw_subjects '
        'GROUP BY actual_arm","purpose":"Count subjects by actual arm."}'
    )
    version_id = uuid4()

    proposal = asyncio.run(
        propose_clinical_sql(model, dataset_version_id=version_id, question="How many per arm?")
    )

    assert proposal.dataset_version_id == version_id
    assert proposal.confirmation_required
    assert proposal.validated_sql.endswith("LIMIT 100")
    assert model.requests[0].question == "How many per arm?"
    assert set(model.requests[0].approved_schema) == {
        "vw_subjects",
        "vw_adverse_events",
        "vw_laboratory_results",
    }


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (
            '{"candidate_sql":null,"purpose":"Not in the approved views."}',
            SQLPlanningErrorCode.QUERY_NOT_SUPPORTED,
        ),
        (
            '{"candidate_sql":"DELETE FROM dm_subject","purpose":"No."}',
            SQLPlanningErrorCode.INVALID_MODEL_RESPONSE,
        ),
        (
            '{"candidate_sql":"SELECT secret FROM vw_subjects","purpose":"No."}',
            SQLPlanningErrorCode.INVALID_MODEL_RESPONSE,
        ),
        (
            '{"candidate_sql":"SELECT * FROM vw_subjects","purpose":"  "}',
            SQLPlanningErrorCode.INVALID_MODEL_RESPONSE,
        ),
        ("not JSON", SQLPlanningErrorCode.INVALID_MODEL_RESPONSE),
        (SQLModelError("provider failed"), SQLPlanningErrorCode.MODEL_UNAVAILABLE),
    ],
)
def test_unsafe_or_invalid_model_response_is_rejected(
    response: str | Exception, expected_code: SQLPlanningErrorCode
) -> None:
    with pytest.raises(SQLPlanningError) as failure:
        asyncio.run(
            propose_clinical_sql(
                FakeSQLModel(response), dataset_version_id=uuid4(), question="Draft a query"
            )
        )
    assert failure.value.code is expected_code
