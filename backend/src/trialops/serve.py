"""Start the local API with an event loop compatible with async Psycopg."""

import argparse
import asyncio
import sys

import uvicorn


def main() -> None:
    """Select Uvicorn's Windows-compatible loop factory before serving."""
    parser = argparse.ArgumentParser(description="Run the local TrialOps API")
    parser.add_argument("--env-file", default="../.env")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()

    uvicorn.run(
        "trialops.main:app",
        host="127.0.0.1",
        port=arguments.port,
        env_file=arguments.env_file,
        loop="trialops.serve:selector_loop_factory" if sys.platform == "win32" else "auto",
    )


def selector_loop_factory() -> asyncio.AbstractEventLoop:
    """Use a selector loop because Psycopg's async driver rejects Proactor."""
    return asyncio.SelectorEventLoop()


if __name__ == "__main__":
    main()
