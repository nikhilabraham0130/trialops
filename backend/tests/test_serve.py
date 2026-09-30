"""The development launcher must select a database-compatible event loop."""

import asyncio
import sys
from typing import Any

import pytest

from trialops import serve


def test_selector_loop_factory_returns_compatible_loop() -> None:
    loop = serve.selector_loop_factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


def test_launcher_passes_windows_selector_factory_to_uvicorn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_run(app: str, **kwargs: Any) -> None:
        calls.append((app, kwargs))

    monkeypatch.setattr(sys, "argv", ["trialops.serve", "--env-file", "../.env", "--port", "8001"])
    monkeypatch.setattr(serve.uvicorn, "run", fake_run)
    serve.main()

    assert calls[0][0] == "trialops.main:app"
    assert calls[0][1]["port"] == 8001
    assert calls[0][1]["env_file"] == "../.env"
    assert calls[0][1]["loop"] == (
        "trialops.serve:selector_loop_factory" if sys.platform == "win32" else "auto"
    )
