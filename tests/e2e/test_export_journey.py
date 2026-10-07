"""MIX-13 UI export journeys J1/J2 against the contract stub, via browser download capture.

Asserts the export control's contract clauses: the selected role travels as X-Role (C3),
the downloaded bytes are BOM + API bytes (C4), the filename is the server-stated name from
Content-Disposition (C1/C7), the error surface is #status with the response's status code
(C5), and the parity rule: export rows == the ids the page table shows for that role.
Retarget to the real backend endpoint when MIX-12 merges (integration milestone).
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

BOM = b"\xef\xbb\xbf"
CD_RE = re.compile(r'^attachment; filename="(reports-\d{4}-\d{2}-\d{2}\.csv)"$')  # C7
STUB_APP = "tests.e2e.export_stub_app:app"
# MIX-23 A4: same ids/restricted flags as the built-in set, but non-ASCII + neutralisation
# cells, so the C4 byte-parity assertions run over multi-byte bytes now and after the MIX-12
# retarget keeps launching via the same C6-B seam (the gate's non-blocking tripwire ask).
FIXTURE_J1 = Path(__file__).parent / "reports_j1_fixture.json"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _spawn(extra_env: dict[str, str] | None = None) -> tuple[subprocess.Popen, str]:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", STUB_APP, "--port", str(port), "--log-level", "warning"],
        env={**os.environ, **(extra_env or {})},
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)  # noqa: S310 - loopback http only
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("export stub did not start")
    return proc, url


@pytest.fixture(scope="module")
def stub() -> str:
    proc, url = _spawn({"REPORTS_FIXTURE_FILE": str(FIXTURE_J1)})
    yield url
    proc.terminate()
    proc.wait(timeout=10)


def _api_export(url: str, role: str) -> tuple[dict[str, str], bytes]:
    req = urllib.request.Request(url + "/api/reports/export")  # noqa: S310 - loopback http only
    req.add_header("X-Role", role)
    with urllib.request.urlopen(req, timeout=5) as res:  # noqa: S310
        return dict(res.headers), res.read()


def _download_as(page: Page, url: str, role: str) -> bytes:
    page.goto(url + "/")
    expect(page.locator("#status")).to_have_text("3 reports")
    if role != "viewer":
        page.get_by_label("role").select_option(role)
        expect(page.locator("#reports tbody tr")).to_have_count(4)
    with page.expect_download() as info:
        page.get_by_role("button", name="Export CSV").click()
    download = info.value
    assert re.fullmatch(r"reports-\d{4}-\d{2}-\d{2}\.csv", download.suggested_filename)
    body = Path(download.path()).read_bytes()
    assert body.startswith(BOM)
    return body


def _table_ids(page: Page) -> list[str]:
    return page.eval_on_selector_all("#reports tbody tr", "rs => rs.map(r => r.dataset.id)")


def _rows(body: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(body[len(BOM) :].decode("utf-8"))))


def test_j1_viewer_export_matches_parity_set(page: Page, stub: str):
    body = _download_as(page, stub, "viewer")
    headers, api_body = _api_export(stub, "viewer")
    assert body == BOM + api_body  # C4 byte-equality
    m = CD_RE.fullmatch(headers["content-disposition"])
    assert m, headers.get("content-disposition")
    # server-stated name is what the browser used; JS never computes its own (C1)
    rows = _rows(body)
    assert rows[0] == ["id", "title", "owner", "rows"]  # C2 header, exact
    assert [r[0] for r in rows[1:]] == _table_ids(page) == ["1", "2", "4"]  # parity rule
    assert not any(r[0] == "3" for r in rows[1:])  # J4 structural: no id-3 row (C3)
    assert not any("Payroll summary" in cell for row in rows[1:] for cell in row)


def test_j2_admin_export_parity_and_positive_control(page: Page, stub: str):
    body = _download_as(page, stub, "admin")
    headers, api_body = _api_export(stub, "admin")
    assert body == BOM + api_body
    m = CD_RE.fullmatch(headers["content-disposition"])
    assert m and m.group(1) == "reports-" + time.strftime("%Y-%m-%d", time.gmtime()) + ".csv"
    rows = _rows(body)
    assert rows[0] == ["id", "title", "owner", "rows"]
    assert [r[0] for r in rows[1:]] == _table_ids(page) == ["1", "2", "3", "4"]
    assert any("Payroll summary" in cell for row in rows[1:] for cell in row)  # never vacuous


def test_role_change_file_differs_by_parity_delta(page: Page, stub: str):
    page.goto(stub + "/")
    expect(page.locator("#reports tbody tr")).to_have_count(3)
    with page.expect_download() as info:
        page.get_by_role("button", name="Export CSV").click()
    viewer_ids = {r[0] for r in _rows(Path(info.value.path()).read_bytes())[1:]}
    page.get_by_label("role").select_option("admin")
    expect(page.locator("#reports tbody tr")).to_have_count(4)
    with page.expect_download() as info:
        page.get_by_role("button", name="Export CSV").click()
    admin_ids = {r[0] for r in _rows(Path(info.value.path()).read_bytes())[1:]}
    assert admin_ids - viewer_ids == {"3"}  # C8: role change ⇒ exactly the parity delta
    assert viewer_ids < admin_ids


def test_error_status_code_surfaced_in_status_line(page: Page, stub: str):
    downloads: list = []
    page.on("download", lambda d: downloads.append(d))
    page.goto(stub + "/")
    expect(page.locator("#reports tbody tr")).to_have_count(3)
    page.route(stub + "/api/reports/export", lambda route: route.fulfill(status=404))
    page.get_by_role("button", name="Export CSV").click()
    expect(page.locator("#status")).to_have_text("Error 404")
    page.wait_for_timeout(250)
    assert downloads == []  # failed export never downloads


def test_network_failure_surfaced_in_status_line(page: Page, stub: str):
    page.goto(stub + "/")
    expect(page.locator("#reports tbody tr")).to_have_count(3)
    page.route(stub + "/api/reports/export", lambda route: route.abort())
    page.get_by_role("button", name="Export CSV").click()
    expect(page.locator("#status")).to_have_text("Export failed")


def test_empty_permitted_set_downloads_header_only(page: Page, tmp_path: Path):
    fixture = tmp_path / "empty.json"
    fixture.write_text(json.dumps([]), encoding="utf-8")
    proc, url = _spawn({"REPORTS_FIXTURE_FILE": str(fixture)})
    try:
        page.goto(url + "/")
        expect(page.locator("#status")).to_have_text("No reports")
        with page.expect_download() as info:
            page.get_by_role("button", name="Export CSV").click()
        body = Path(info.value.path()).read_bytes()
        assert body == BOM + b"id,title,owner,rows\r\n"  # C5: 24 browser bytes (C4)
        assert _rows(body) == [["id", "title", "owner", "rows"]]
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.parametrize(
    "disposition",
    [
        None,  # header absent
        "attachment; filename=reports-2026-10-07.csv",  # unquoted filename parameter
        "attachment; filename*=UTF-8''reports-2026-10-07.csv",  # extended form only
    ],
    ids=["absent", "unquoted", "extended-only"],
)
def test_off_contract_200_fails_closed(page: Page, stub: str, disposition):
    # MIX-23 A2/A3: C1 forbids a client-computed name, so an off-contract 200 carrying no
    # parseable quoted filename must not download and must surface the existing failure string.
    downloads: list = []
    page.on("download", lambda d: downloads.append(d))
    page.goto(stub + "/")
    expect(page.locator("#reports tbody tr")).to_have_count(3)
    headers = {"Content-Type": "text/csv"}
    if disposition is not None:
        headers["Content-Disposition"] = disposition
    page.route(
        stub + "/api/reports/export",
        lambda route: route.fulfill(status=200, body="id,title,owner,rows\r\n", headers=headers),
    )
    page.get_by_role("button", name="Export CSV").click()
    expect(page.locator("#status")).to_have_text("Export failed")
    page.wait_for_timeout(250)
    assert downloads == []


def test_j1_fixture_cells_cover_multibyte_and_neutralisation(stub: str):
    # MIX-23 A4 tripwire: proves the module stub booted from reports_j1_fixture.json, i.e. the
    # J1 byte-parity assertion above covers multi-byte and neutralisation-interaction bytes.
    _, api_body = _api_export(stub, "admin")
    assert "Café — naïve ☃".encode() in api_body
    assert "日本語テスト".encode() in api_body
    assert "Ωmega".encode() in api_body
    assert b"'=SUM(A1)" in api_body  # C4 ¶5: '='-lead neutralised with a leading apostrophe
    assert b'"a, =b"' in api_body  # C4 ¶1: comma cell minimally quoted (RFC 4180)
