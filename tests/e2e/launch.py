"""Shared test-only uvicorn launcher for the browser suites.

Same launch contract as ``tests/e2e/conftest.py`` (``python -m uvicorn <spec> --port <free>``
from the repo root), plus an env override so a test can point the C6-B Layer B seam
(``REPORTS_FIXTURE_FILE``) at a fixture file. ``app_spec`` is always a test-side module
(``tests.e2e.fixture_app:app``); production code never reads the seam variable (C6 purity).
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator, Mapping

APP_SPEC = "tests.e2e.fixture_app:app"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def served(app_spec: str = APP_SPEC, env: Mapping[str, str] | None = None) -> Iterator[str]:
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", app_spec, "--port", str(port), "--log-level", "warning"],
        env={**os.environ, **(env or {})},
    )
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(url + "/healthz", timeout=1)  # noqa: S310 - loopback http only
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError(f"{app_spec} did not start")
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)
