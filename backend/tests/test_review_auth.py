"""Local review credentials are secret, distinct, and checked on the backend."""

import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from trialops.core.config import RuntimeEnvironment, Settings
from trialops.main import create_app
from trialops.reviews.auth import ReviewRole, get_review_actor


def _request(settings: Settings) -> Request:
    app = create_app(settings)
    return Request({"type": "http", "app": app, "path": "/", "method": "GET", "headers": []})


def test_configured_tokens_identify_distinct_backend_actors() -> None:
    settings = Settings(
        env=RuntimeEnvironment.TEST,
        analyst_token=SecretStr("a" * 32),
        reviewer_token=SecretStr("r" * 32),
    )
    request = _request(settings)
    analyst = get_review_actor(request, "Bearer " + "a" * 32)
    reviewer = get_review_actor(request, "Bearer " + "r" * 32)
    assert analyst.id != reviewer.id
    assert analyst.role is ReviewRole.ANALYST
    assert reviewer.role is ReviewRole.REVIEWER
    assert "a" * 32 not in repr(settings)


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic " + "a" * 32])
def test_missing_or_wrong_token_is_rejected(authorization: str | None) -> None:
    settings = Settings(
        env=RuntimeEnvironment.TEST,
        analyst_token=SecretStr("a" * 32),
        reviewer_token=SecretStr("r" * 32),
    )
    with pytest.raises(HTTPException) as failure:
        get_review_actor(_request(settings), authorization)
    assert failure.value.status_code == 401


def test_unconfigured_review_is_unavailable() -> None:
    with pytest.raises(HTTPException) as failure:
        get_review_actor(_request(Settings(env=RuntimeEnvironment.TEST)), "Bearer " + "a" * 32)
    assert failure.value.status_code == 503


@pytest.mark.parametrize(
    ("analyst", "reviewer"),
    [("short", "r" * 32), ("a" * 32, None), ("same" * 8, "same" * 8)],
)
def test_review_tokens_must_be_long_distinct_and_paired(
    analyst: str | None, reviewer: str | None
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            env=RuntimeEnvironment.TEST,
            analyst_token=SecretStr(analyst) if analyst else None,
            reviewer_token=SecretStr(reviewer) if reviewer else None,
        )
