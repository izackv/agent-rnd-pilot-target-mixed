"""MIX-14 composed-branch integration matrix — what neither PR alone could show.

Backend (MIX-12, merged to ``main``) and UI (MIX-13, branch) are exercised together here: every
leg launches ``app.main:app`` through the C6-B Layer B seam (``tests.e2e.fixture_app``), so the
browser control, the shipped emitter and the shipped permission path are the same code the
feature releases with — no contract stub anywhere.

Traceability: test-plan §1 J4 (every cell + control), §2 adversarial FX through the named seam,
§3 AP-1/AP-2/AP-3 cross-surface mechanics, §4 RG-1 repeated downloads.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e.launch import APP_SPEC, served

BOM = b"\xef\xbb\xbf"
EXPORT_PATH = "/api/reports/export"
CD_RE = re.compile(r'^attachment; filename="(reports-[0-9]{4}-[0-9]{2}-\d{2}\.csv)"$')  # C7
HEADER = b"id,title,owner,rows\r\n"

NFC = "\u00c9milie \u00c5snes"
NFD = unicodedata.normalize("NFD", NFC)
LONG = "x" * 32_768
TAB = "a\tb"

# test-plan §2 FX list — one report per adversarial value (id, title, owner, rows, restricted).
# The restricted row reuses the brief's fixture title so J4's guards run on this set as well.
FX_ROWS: list[tuple[int, str, str, int, bool]] = [
    (11, "a, b", "a, b", 1, False),  # FX01 comma in both text columns
    (12, '"quo"ted"', "ops", 2, False),  # FX02 embedded quotes
    (13, "line\nfeed", "ops", 3, False),  # FX03 embedded LF
    (14, "line\r\nfeed", "ops", 4, False),  # FX04 embedded CRLF
    (15, "line\rfeed", "ops", 5, False),  # FX05 lone CR
    (16, '=HYPERLINK("http://x","y")', "ops", 6, False),  # FX06
    (17, "+1+1", "ops", 7, False),  # FX07
    (18, "-2+3", "ops", 8, False),  # FX08
    (19, "@SUM(A1)", "@SUM(A1)", 9, False),  # FX09
    (20, "1-1", "ops", 10, False),  # FX10 no lead trigger
    (21, "00123", "ops", 11, False),  # FX11 numeric-looking text
    (22, "1E+3", "ops", 12, False),  # FX12 numeric-looking text
    (23, TAB, "ops", 13, False),  # FX13 tab is data
    (24, "", "ops", 14, False),  # FX14 empty cell, never a missing one
    (25, " ", "ops", 15, False),  # FX15 single space untouched
    (26, f"a{chr(0x2028)}b", "ops", 16, False),  # FX16 U+2028 is data, not a line break
    (27, NFC, "ops", 17, False),  # FX17 NFC form
    (28, NFD, "ops", 18, False),  # FX18 NFD form — must stay byte-distinct from FX17
    (29, "报告", "ops", 19, False),  # FX19
    (30, "😈", "ops", 20, False),  # FX20
    (31, LONG, "ops", 21, False),  # FX21 32 768 chars, never truncated
    (32, '\'=HYPERLINK("http://x","y")', "ops", 22, False),  # FX22 stored leading apostrophe
    (33, "'=x", "ops", 23, False),  # FX23 stored prefix only (rev 3 C4)
    (34, "-42", "ops", -42, False),  # C2 value-blind: text prefixed, numeric bare
    (903, "Payroll summary", "finance", 310, True),  # restricted at rest
]
FX_EXPECT = {rid: (title, owner, rows) for rid, title, owner, rows, _ in FX_ROWS}
FX_RESTRICTED_ID = str(next(r[0] for r in FX_ROWS if r[4]))
FX_VIEWER_IDS = [str(r[0]) for r in FX_ROWS if not r[4]]
FX_ALL_IDS = [str(r[0]) for r in FX_ROWS]

# Byte-normative field renderings (C4 rev 3 ¶1+¶5, doc ``c4-byte-matrix``): the whole FX corpus,
# spelled as vectors rather than re-derived by a second implementation in this test.
FX_BYTES: dict[int, str] = {
    11: '11,"a, b","a, b",1',
    12: '12,"""quo""ted""",ops,2',
    13: '13,"line\nfeed",ops,3',
    14: '14,"line\r\nfeed",ops,4',
    15: '15,"line\rfeed",ops,5',
    16: '16,"\'=HYPERLINK(""http://x"",""y"")",ops,6',
    17: "17,'+1+1,ops,7",
    18: "18,'-2+3,ops,8",
    19: "19,'@SUM(A1),'@SUM(A1),9",
    20: "20,1-1,ops,10",
    21: "21,00123,ops,11",
    22: "22,1E+3,ops,12",
    23: f"23,{TAB},ops,13",
    24: "24,,ops,14",
    25: "25, ,ops,15",
    26: f"26,a{chr(0x2028)}b,ops,16",
    27: f"27,{NFC},ops,17",
    28: f"28,{NFD},ops,18",
    29: "29,报告,ops,19",
    30: "30,😈,ops,20",
    31: f"31,{LONG},ops,21",
    32: '32,"\'\'=HYPERLINK(""http://x"",""y"")",ops,22',
    33: "33,''=x,ops,23",
    34: "34,'-42,ops,-42",
    903: "903,Payroll summary,finance,310",
}


def _api_export(url: str, role: str | None) -> tuple[dict[str, str], bytes]:
    req = urllib.request.Request(url + EXPORT_PATH)  # noqa: S310 - loopback http only
    if role is not None:
        req.add_header("X-Role", role)
    with urllib.request.urlopen(req, timeout=5) as res:  # noqa: S310
        return dict(res.headers), res.read()


def _click_export(page: Page) -> tuple[str, bytes]:
    with page.expect_download() as info:
        page.get_by_role("button", name="Export CSV").click()
    download = info.value
    return download.suggested_filename, Path(download.path()).read_bytes()


def _parse(body: bytes) -> list[list[str]]:
    """stdlib csv parse of a browser (BOM + UTF-8) or API (UTF-8) body, no newline rewriting."""
    return list(csv.reader(io.StringIO(body.removeprefix(BOM).decode("utf-8")), strict=True))


def _strip_one_apostrophe(cell: str) -> str:
    """QA fidelity inverse (C4 ¶5): strip exactly one leading U+0027 iff present."""
    return cell[1:] if cell.startswith("'") else cell


def _assert_no_restricted(rows: list[list[str]], restricted_id: str) -> None:
    """J4 guards G1–G3, asserted on the parsed file only — never a substring grep of raw bytes."""
    assert rows[0] == ["id", "title", "owner", "rows"]  # G2: `restricted` is never a column
    assert all(len(row) == 4 for row in rows)
    assert all(row[0] != restricted_id for row in rows[1:])  # G1
    assert not any("Payroll summary" in cell for row in rows for cell in row)  # G3


def _route_role(page: Page, url: str, role: str | None) -> list[dict[str, str]]:
    """Rewrite only the export request's X-Role header and pass the server's own answer through.

    The returned list proves the treatment reached the wire; without it a silently-ignored
    rewrite would make every cell below pass vacuously on the selector's header.
    """
    seen: list[dict[str, str]] = []

    def handler(route: Route) -> None:
        headers = dict(route.request.headers)
        headers.pop("x-role", None)
        if role is not None:
            headers["x-role"] = role
        seen.append(headers)
        route.fulfill(response=route.fetch(headers=headers))

    page.route(url + EXPORT_PATH, handler)
    return seen


@pytest.fixture(scope="module")
def fx_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Layer B (C6-B): the adversarial corpus, launch-effective with no restart."""
    fixture = tmp_path_factory.mktemp("fx") / "adversarial.json"
    entries = [
        {"id": rid, "title": title, "owner": owner, "rows": rows, "restricted": restricted}
        for rid, title, owner, rows, restricted in FX_ROWS
    ]
    fixture.write_text(json.dumps(entries), "utf-8")
    with served(APP_SPEC, {"REPORTS_FIXTURE_FILE": str(fixture)}) as url:
        yield url


@pytest.fixture(scope="module")
def builtin_server() -> Iterator[str]:
    """Layer B with the seam unset ⇒ the built-in set, identical on both surfaces (C6-B)."""
    with served(APP_SPEC) as url:
        yield url


# --- §1 J4: browser surface × role treatments, plus the non-vacuous control ----------


@pytest.mark.parametrize(
    ("wire_role", "via_route"),
    [(None, False), (None, True), ("guest", True), ("ADMIN", True)],
    ids=["T1-viewer-selector", "T2-header-omitted", "T3-unknown-guest", "T4-case-variant"],
)
def test_j4_browser_cells_never_expose_restricted(
    page: Page, builtin_server: str, wire_role, via_route
):
    page.goto(builtin_server + "/")
    expect(page.locator("#status")).to_have_text("3 reports")
    seen: list[dict[str, str]] = []
    if via_route:
        seen = _route_role(page, builtin_server, wire_role)
    else:
        assert page.evaluate("document.getElementById('role').value") == "viewer"
    _, body = _click_export(page)
    if via_route:
        assert seen, "the export request never matched the route"
        assert seen[-1].get("x-role") == wire_role if wire_role else "x-role" not in seen[-1]
    _assert_no_restricted(_parse(body), "3")


def test_j4_positive_control_admin_in_browser(page: Page, builtin_server: str):
    """Admin on the shipped UI must contain the restricted row, else every cell above is vacuous."""
    page.goto(builtin_server + "/")
    page.get_by_label("role").select_option("admin")
    expect(page.locator("#reports tbody tr")).to_have_count(4)
    _, body = _click_export(page)
    rows = _parse(body)
    assert [row[0] for row in rows[1:]] == ["1", "2", "3", "4"]
    assert any(row[0] == "3" for row in rows[1:])
    assert any("Payroll summary" in cell for row in rows for cell in row)


def test_j4_header_rewrite_reaches_the_server(page: Page, builtin_server: str):
    """Tripwire for the J4 harness itself: a route-set admin header must widen the set."""
    page.goto(builtin_server + "/")
    seen = _route_role(page, builtin_server, "admin")
    _, body = _click_export(page)
    assert seen and seen[-1].get("x-role") == "admin"
    assert [row[0] for row in _parse(body)[1:]] == ["1", "2", "3", "4"]


# --- §2 adversarial corpus via the seam, in the browser ------------------------------


def test_fx_viewer_download_fidelity_and_guards(page: Page, fx_server: str):
    page.goto(fx_server + "/")
    expect(page.locator("#reports tbody tr")).to_have_count(len(FX_VIEWER_IDS))
    _, body = _click_export(page)
    rows = _parse(body)
    _assert_no_restricted(rows, FX_RESTRICTED_ID)  # J1(d): guards run on every export
    assert [row[0] for row in rows[1:]] == FX_VIEWER_IDS  # AP-1 order == id ascending
    _check_fidelity(rows)


def test_fx_admin_download_fidelity_and_order(page: Page, fx_server: str):
    page.goto(fx_server + "/")
    page.get_by_label("role").select_option("admin")
    expect(page.locator("#reports tbody tr")).to_have_count(len(FX_ALL_IDS))
    name, body = _click_export(page)
    rows = _parse(body)
    assert [row[0] for row in rows[1:]] == FX_ALL_IDS
    _check_fidelity(rows)
    assert name.startswith("reports-")  # C1: server-stated name, never a client-computed one


def _check_fidelity(rows: list[list[str]]) -> None:
    """AD-1: parsed cell == stored value exactly, after at most one documented prefix (C4 ¶5)."""
    for row in rows[1:]:
        assert len(row) == 4
        title, owner, rows_count = FX_EXPECT[int(row[0])]
        assert _strip_one_apostrophe(row[1]) == title
        assert _strip_one_apostrophe(row[2]) == owner
        assert row[3] == str(rows_count)  # numeric cell: never quoted, never prefixed (C2)


# --- §3 cross-surface mechanics: AP-1/AP-2/AP-3 + C4 byte vectors --------------------


@pytest.mark.parametrize("role", [None, "viewer", "admin"])
def test_cross_surface_bytes_differ_only_by_one_bom(page: Page, fx_server: str, role: str):
    """AP-2 + brief criterion 1: browser bytes == EF BB BF + API bytes, BOM exactly once."""
    page.goto(fx_server + "/")
    selected = "admin" if role == "admin" else "viewer"
    page.get_by_label("role").select_option(selected)
    browser_name, browser_body = _click_export(page)
    headers, api_body = _api_export(fx_server, role)
    assert browser_body == BOM + api_body
    assert browser_body.count(BOM) == 1 and api_body.count(BOM) == 0
    m = CD_RE.fullmatch(headers["content-disposition"])
    assert m, headers.get("content-disposition")
    assert m.group(1) == browser_name  # filename parity: server header == JS-chosen name (C1/C7)
    assert _parse(browser_body) == _parse(api_body)  # AP-1 same matrix on both surfaces


@pytest.mark.parametrize("rid", sorted(FX_BYTES))
def test_c4_byte_vectors_present_in_the_api_body(fx_server: str, rid: int):
    """C4 rev 3 ¶1/¶5 byte outcomes for every FX value, from the shipped emitter."""
    _, api_body = _api_export(fx_server, "admin")
    assert (FX_BYTES[rid] + "\r\n").encode("utf-8") in api_body
    assert api_body.startswith(HEADER)


def test_crlf_is_the_only_terminator_outside_quoted_fields(fx_server: str):
    """AD-3: no bare CR and no bare LF outside quotes; the last record is terminated too."""
    _, api_body = _api_export(fx_server, "admin")
    quoted = False
    i = 0
    while i < len(api_body):
        ch = api_body[i : i + 1]
        if ch == b'"':
            quoted = not quoted
        elif not quoted:
            if ch == b"\n":
                raise AssertionError(f"bare LF at {i}")
            if ch == b"\r":
                assert api_body[i : i + 2] == b"\r\n", f"bare CR at {i}"
                i += 1
        i += 1
    assert api_body.endswith(b"\r\n")


def test_unicode_forms_round_trip_without_normalisation(fx_server: str):
    """AD-4: NFC and NFD stay byte-distinct (C4 ¶2), and the body decodes strict with none."""
    _, api_body = _api_export(fx_server, "admin")
    text = api_body.decode("utf-8")  # strict: raises on any invalid sequence
    assert "\ufffd" not in text
    assert NFC in text and NFD in text
    assert NFC.encode("utf-8") in api_body and NFD.encode("utf-8") in api_body
    nfc_row = next(r for r in _parse(api_body) if r[0] == "27")
    nfd_row = next(r for r in _parse(api_body) if r[0] == "28")
    assert nfc_row[1] != nfd_row[1]
    assert unicodedata.is_normalized("NFC", nfc_row[1])
    assert unicodedata.is_normalized("NFD", nfd_row[1])


def test_declared_encoding_and_media_type_on_both_surfaces(page: Page, fx_server: str):
    """AP-3: text/csv; charset=utf-8 (C1) and the browser body decodes as utf-8-sig identically."""
    page.goto(fx_server + "/")
    _, browser_body = _click_export(page)
    headers, api_body = _api_export(fx_server, None)
    assert headers["content-type"] == "text/csv; charset=utf-8"
    api_text = api_body.decode("utf-8", "strict")
    assert browser_body.decode("utf-8-sig") == api_text


# --- §4 RG-1: repeated downloads, unchanged data -------------------------------------


def test_repeated_downloads_are_byte_identical_on_both_surfaces(page: Page, builtin_server: str):
    page.goto(builtin_server + "/")
    first_name, first_body = _click_export(page)
    second_name, second_body = _click_export(page)
    assert first_body == second_body and first_name == second_name
    headers, api_first = _api_export(builtin_server, "viewer")
    _, api_second = _api_export(builtin_server, "viewer")
    assert api_first == api_second
    assert api_first == _api_export(builtin_server, None)[1]  # absent header == viewer (C3)
    assert CD_RE.fullmatch(headers["content-disposition"])  # stable server-stated name
    assert second_body == BOM + api_first  # cross-pair per AP-2, same UTC day
