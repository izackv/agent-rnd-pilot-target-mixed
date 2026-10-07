"""C6 Layer B seam boot tests (contract rev 3; MIX-21 C6-B blocker).

``tests/e2e/fixture_app.py`` must be launch-effective and fail-loud, asserted
here through real subprocesses so the module-global load happens at boot and
stays isolated from the rest of the suite:

- valid ``REPORTS_FIXTURE_FILE`` ⇒ a real uvicorn serves exactly the fixture
  rows (JSON API, role-filtered, and the C6 seam feeding the export path);
- unset env var ⇒ the built-in set, i.e. ≡ ``app.main:app``;
- type-bad or structure-bad fixture ⇒ import raises (aborting startup) and a
  real uvicorn launch never becomes healthy.
"""

from __future__ import annotations

import csv
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = "tests.e2e.fixture_app"
HEALTH_TIMEOUT = 15.0

GOOD = [
    {"id": 91, "title": "Fixture one", "owner": "qa", "rows": 3, "restricted": False},
    {"id": 90, "title": "Fixture two", "owner": "finance", "rows": 7, "restricted": True},
]

BAD_FIXTURES = {
    "type-bad id is str": [{**GOOD[0], "id": "91"}],
    "type-bad rows is str": [{**GOOD[0], "rows": "3"}],
    "type-bad restricted is int": [{**GOOD[0], "restricted": 1}],
    "type-bad title is null": [{**GOOD[0], "title": None}],
    "type-bad id is bool": [{**GOOD[0], "id": True}],
    "structure-bad missing key": [{"id": 91, "title": "t", "owner": "o", "rows": 3}],
    "structure-bad extra key": [{**GOOD[0], "restricted_": False}],
    "structure-bad root is object": {"id": 91},
    "structure-bad entry is list": [[91, "t", "o", 3, False]],
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _fixture_path(tmp_path: Path, entries: object) -> str:
    path = tmp_path / "reports.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return str(path)


def _child_env(fixture_file: str | None) -> dict[str, str]:
    env = dict(os.environ)
    if fixture_file is None:
        env.pop("REPORTS_FIXTURE_FILE", None)
    else:
        env["REPORTS_FIXTURE_FILE"] = fixture_file
    return env


def _launch(fixture_file: str | None) -> tuple[subprocess.Popen, str]:
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            f"{MODULE}:app",
            "--port",
            str(port),
            "--log-level",
            "critical",
        ],
        cwd=ROOT,
        env=_child_env(fixture_file),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc, f"http://127.0.0.1:{port}"


def _wait_exit(proc: subprocess.Popen, timeout: float) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code = proc.poll()
        if code is not None:
            return code
        time.sleep(0.05)
    return None


def _wait_healthy(proc: subprocess.Popen, url: str, timeout: float) -> str | None:
    """Return None once /healthz answers; return a failure report otherwise."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code = proc.poll()
        if code is not None:
            return f"process exited {code}: {proc.communicate(timeout=5)[0]}"
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=0.5) as r:  # noqa: S310 - loopback
                if r.status == 200:
                    return None
        except (OSError, urllib.error.URLError):
            time.sleep(0.1)
    proc.terminate()
    return f"not healthy in {timeout}s: {proc.communicate(timeout=5)[0]}"


def _get(url: str, role: str | None = None) -> tuple[int, bytes]:
    headers = {} if role is None else {"X-Role": role}
    req = urllib.request.Request(url, headers=headers)  # noqa: S310 - loopback fixed URL
    try:
        with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310 - loopback
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.status, e.read()


def test_valid_fixture_is_what_the_server_serves(tmp_path):
    proc, url = _launch(_fixture_path(tmp_path, GOOD))
    try:
        problem = _wait_healthy(proc, url, HEALTH_TIMEOUT)
        assert problem is None, problem
        status, admin_body = _get(url + "/api/reports", role="admin")
        assert status == 200
        assert json.loads(admin_body) == GOOD  # C6-B: launch-effective, rows match the file
        status, body = _get(url + "/api/reports")
        assert json.loads(body) == [GOOD[0]]  # C3 filter applies to fixture data too
        status, body = _get(url + "/api/reports/export", role="admin")
        assert status == 200
        rows = list(csv.reader(io.StringIO(body.decode("utf-8")), strict=True))
        assert rows[0] == ["id", "title", "owner", "rows"]
        # C3 parity by construction: emitter order == served JSON order (file order;
        # the built-in ids happen to already be ascending, so only unsorted seam
        # data can prove the emitter never re-sorts).
        assert [r[0] for r in rows[1:]] == [str(r["id"]) for r in json.loads(admin_body)]
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_unset_env_var_serves_the_builtin_set(tmp_path):
    proc, url = _launch(None)
    try:
        problem = _wait_healthy(proc, url, HEALTH_TIMEOUT)
        assert problem is None, problem
        status, body = _get(url + "/api/reports")
        assert status == 200
        assert [r["id"] for r in json.loads(body)] == [1, 2, 4]  # ≡ app.main:app (docstring)
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.parametrize("entries", BAD_FIXTURES.values(), ids=BAD_FIXTURES.keys())
def test_malformed_fixture_raises_during_import(tmp_path, entries):
    proc = subprocess.run(
        [sys.executable, "-c", f"import {MODULE}"],
        cwd=ROOT,
        env=_child_env(_fixture_path(tmp_path, entries)),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "fixture" in proc.stderr, proc.stderr  # raises from the validator, not elsewhere


def test_type_bad_fixture_aborts_a_real_launch(tmp_path):
    proc, url = _launch(_fixture_path(tmp_path, [{**GOOD[0], "id": "91"}]))
    try:
        code = _wait_exit(proc, HEALTH_TIMEOUT)
        assert code is not None and code != 0, "uvicorn must exit non-zero on a type-bad fixture"
        problem = _wait_healthy(proc, url, 2.0)
        assert problem is not None  # never becomes healthy
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=10)
