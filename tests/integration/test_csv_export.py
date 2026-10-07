"""Integration tests for GET /api/reports/export — contract rev 3, API surface.

Traced clauses: C1 (endpoint/headers/route order), C2 (schema bytes, order),
C3 (permission parity + matrix, SECURITY-RELEVANT), C4 (BOM-free UTF-8 on the
API path), C5 (error cases + shape table), C6 Layer A seam (empty and hostile
seeds), C7 (header-injection regex).

J3 = role matrix incl. case variants and the C3 probes.
J4 = restricted never appears, asserted STRUCTURALLY (stdlib csv parse,
cell-scoped — never raw byte-grep), with a non-vacuous admin positive control.
"""

from __future__ import annotations

import csv
import io
import re
import urllib.parse
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.data import Report
from app.main import app

URL = "/api/reports/export"
HEADER = b"id,title,owner,rows\r\n"
BUILTIN_VIEWER_IDS = ["1", "2", "4"]
BUILTIN_ADMIN_IDS = ["1", "2", "3", "4"]

client = TestClient(app, follow_redirects=False)


def parse(body: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(body.decode("utf-8")), strict=True))


def get_ids(body: bytes) -> list[str]:
    return [row[0] for row in parse(body)[1:]]


def expected_disposition() -> str:
    date = datetime.now(UTC).date().strftime("%Y-%m-%d")
    return f'attachment; filename="reports-{date}.csv"'


# --- C1: success surface -------------------------------------------------------


def test_canonical_get_is_200_csv_with_exact_headers():
    r = client.get(URL)
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == expected_disposition()
    assert parse(r.content)[0] == ["id", "title", "owner", "rows"]


def test_accept_header_never_changes_status_media_type_or_bytes():
    baseline = client.get(URL, headers={"X-Role": "admin"}).content
    for accept in ["*/*", "application/json", "text/html", "nonsense/xyz"]:
        r = client.get(URL, headers={"X-Role": "admin", "Accept": accept})
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/csv; charset=utf-8"
        assert r.content == baseline


def test_api_bytes_are_pure_utf8_without_bom():
    body = client.get(URL, headers={"X-Role": "admin"}).content
    assert not body.startswith(b"\xef\xbb\xbf")
    assert not body.decode("utf-8").startswith("\ufeff")
    body.decode("utf-8", "strict")  # C4 §2: decodes with no replacement chars


# --- C1/C7: Content-Disposition can carry nothing hostile ----------------------


DISPOSITION_RE = re.compile(r'^attachment; filename="reports-[0-9]{4}-[0-9]{2}-[0-9]{2}\.csv"$')


@pytest.mark.parametrize("role", [None, "viewer", "admin", "guest", "ADMIN"])
def test_content_disposition_matches_injection_safe_regex(role):
    hs = {} if role is None else {"X-Role": role}
    cd = client.get(URL, headers=hs).headers["content-disposition"]
    assert DISPOSITION_RE.match(cd), cd  # C7: closes the header-injection surface
    assert "\r" not in cd and "\n" not in cd
    assert cd.split("filename=")[1].lower().find("admin") == -1  # C1: role never in name


def test_filename_never_derives_from_report_data(seeded_reports):
    # C7: a seam title/owner carrying CRLF must not reach the header value.
    seeded_reports([Report(7, 'x\r\nSet-Cookie: a=1"', "o\r\nInj: 1", 1)])
    cd = client.get(URL, headers={"X-Role": "admin"}).headers["content-disposition"]
    assert DISPOSITION_RE.match(cd), cd


# --- C2: schema bytes ----------------------------------------------------------


@pytest.mark.parametrize("role", [None, "admin"])
def test_header_line_is_the_first_21_bytes_for_every_role(role):
    hs = {} if role is None else {"X-Role": role}
    assert client.get(URL, headers=hs).content[:21] == HEADER


def test_viewer_body_bytes_are_the_permitted_set_only():
    assert client.get(URL).content == HEADER + (
        b"1,Monthly usage,ops,1200\r\n"
        b"2,Error budget,sre,48\r\n"
        b"4,Signup funnel,growth,5200\r\n"
    )


def test_numeric_fields_never_quoted_or_prefixed_even_when_negative(seeded_reports):
    seeded_reports([Report(1, "t", "o", -42), Report(2, "=t", "o", 0)])
    assert client.get(URL).content == HEADER + b"1,t,o,-42\r\n2,'=t,o,0\r\n"


def test_row_order_is_id_ascending_on_wire():
    body = client.get(URL, headers={"X-Role": "admin"}).content
    assert get_ids(body) == BUILTIN_ADMIN_IDS


# --- C3: permission parity — SECURITY-RELEVANT ---------------------------------

# Normative parity test (C3 §1): for any header value H, export row ids ==
# the ids of GET /api/reports with the same header, same process, same data.
ROLE_PROBES: list = [
    None,  # header omitted
    "viewer",
    "admin",
    "guest",
    "ADMIN",
    "Admin",
    "aDmIn",
    " admin",
    "admin ",
    "administrators",
    "role=admin",
    "",
]


@pytest.mark.parametrize("role", ROLE_PROBES)
def test_export_parity_with_list_endpoint(role):
    hs = {} if role is None else {"X-Role": role}
    listing = client.get("/api/reports", headers=hs).json()
    export_ids = get_ids(client.get(URL, headers=hs).content)
    assert export_ids == [str(r["id"]) for r in listing]
    assert export_ids == (BUILTIN_ADMIN_IDS if role == "admin" else BUILTIN_VIEWER_IDS)


def test_duplicated_x_role_first_occurrence_decides():
    # C1 §duplicates: Starlette's lookup feeds _role the first occurrence.
    viewer_first = client.get(
        URL, headers=[("X-Role", "viewer"), ("X-Role", "admin")]
    ).content
    admin_first = client.get(
        URL, headers=[("X-Role", "admin"), ("X-Role", "viewer")]
    ).content
    assert get_ids(viewer_first) == BUILTIN_VIEWER_IDS
    assert get_ids(admin_first) == BUILTIN_ADMIN_IDS


@pytest.mark.parametrize(
    "probe",
    ["?role=admin", "?X-Role=admin", "?id=3", "?restricted=true", "?format=json"],
)
def test_query_params_never_widen_narrow_or_reorder(probe):
    assert client.get(URL + probe).content == client.get(URL).content
    assert client.get(URL + probe, headers={"X-Role": "admin"}).content == client.get(
        URL, headers={"X-Role": "admin"}
    ).content


def test_request_body_never_shadows_the_header():
    baseline = client.get(URL).content
    r = client.request("GET", URL, content=b'{"role": "admin"}')
    assert r.status_code == 200
    assert r.content == baseline


# --- J4: restricted never leaks — structural, cell-scoped -----------------------


@pytest.mark.parametrize("role", [None, "viewer", "guest", "ADMIN", " admin"])
def test_j4_restricted_never_in_any_cell_structurally(role):
    hs = {} if role is None else {"X-Role": role}
    rows = parse(client.get(URL, headers=hs).content)
    assert rows[0] == ["id", "title", "owner", "rows"]  # no `restricted` column (C2)
    assert all(len(row) == 4 for row in rows)
    assert all(row[0] != "3" for row in rows[1:])
    cells = [cell for row in rows for cell in row]
    assert not any("Payroll summary" in cell for cell in cells)


def test_j4_positive_control_is_non_vacuous():
    # Without this row the J4 assertions above could pass vacuously (C3 matrix).
    admin_rows = parse(client.get(URL, headers={"X-Role": "admin"}).content)
    assert ["3", "Payroll summary", "finance", "310"] in admin_rows


# --- C5: empty, error and normative shape table ---------------------------------


def test_empty_permitted_set_is_200_header_only_21_bytes(seeded_reports):
    seeded_reports([])
    for hs in [{}, {"X-Role": "admin"}]:
        r = client.get(URL, headers=hs)
        assert r.status_code == 200
        assert r.content == HEADER
        assert len(r.content) == 21


def test_restricted_only_seed_yields_header_only_for_viewer_but_row_for_admin(
    seeded_reports,
):
    seeded_reports([Report(3, "Payroll summary", "finance", 310, restricted=True)])
    assert client.get(URL).content == HEADER
    assert client.get(URL, headers={"X-Role": "admin"}).content == (
        HEADER + b"3,Payroll summary,finance,310\r\n"
    )


@pytest.mark.parametrize("role", ["admin", "ADMIN", "guest", None])
def test_never_401_or_403_for_any_role(role):
    hs = {} if role is None else {"X-Role": role}
    assert client.get(URL, headers=hs).status_code == 200


def test_existing_endpoints_unchanged():
    missing = client.get("/api/reports/999")
    hidden = client.get("/api/reports/3")
    assert missing.status_code == 404 and hidden.status_code == 404
    assert hidden.json() == missing.json() == {"detail": "report not found"}
    assert client.get("/api/reports/abc").status_code == 422


def test_static_route_is_registered_before_the_int_route():
    # C1 route order: canonical export answers, and never as {report_id}.
    assert client.get(URL).status_code == 200
    assert client.get("/api/reports").status_code == 200


class TestShapeTable:  # C5 table, probed normative on the bound stack
    def test_get_canonical_is_200(self):
        assert client.get(URL).status_code == 200

    def test_head_canonical_is_405_allow_get_empty_body(self):
        r = client.head(URL)
        assert r.status_code == 405
        assert r.headers.get("allow") == "GET"
        assert r.content == b""

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_other_methods_are_405_json_detail(self, method):
        r = getattr(client, method)(URL)
        assert r.status_code == 405
        assert r.json() == {"detail": "Method Not Allowed"}

    def test_trailing_slash_is_307_to_canonical_with_original_query(self):
        r = client.get(URL + "/?format=json")
        assert r.status_code == 307
        loc = urllib.parse.urlparse(r.headers["location"])
        assert loc.path == URL
        assert urllib.parse.parse_qs(loc.query) == {"format": ["json"]}

    def test_deeper_path_is_404_json(self):
        r = client.get(URL + "/extra")
        assert r.status_code == 404
        assert r.json() == {"detail": "Not Found"}

    @pytest.mark.parametrize("path", ["/api/reports/export.csv", "/api/reports/Export"])
    def test_alias_and_name_case_go_to_int_route_422_never_csv(self, path):
        r = client.get(path)
        assert r.status_code == 422
        assert "report_id" in r.text
        assert b"title,owner" not in r.content  # never CSV bytes on this shape

    @pytest.mark.parametrize("path", ["/API/reports/export", "/api/Reports/export"])
    def test_path_case_variants_are_404(self, path):
        assert client.get(path).status_code == 404


# --- C2/C4: determinism (byte-equality of repeated downloads) ------------------


@pytest.mark.parametrize("role", [None, "admin"])
def test_repeated_downloads_are_byte_identical(role):
    hs = {} if role is None else {"X-Role": role}
    first = client.get(URL, headers=hs)
    second = client.get(URL, headers=hs)
    assert first.content == second.content  # same role + unchanged data (C2)
    assert first.headers["content-disposition"] == second.headers["content-disposition"]
