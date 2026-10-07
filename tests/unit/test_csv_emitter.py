"""Unit tests for the CSV emitter (contract rev 3, C2/C4) and the C6 Layer A seam.

Every row of the rev-3 C4 byte-matrix (doc ``c4-byte-matrix`` on the contract
issue) is traced here byte-exactly, plus the QA fidelity inverse for a
trigger-led corpus.
"""

from __future__ import annotations

import csv
import io
import unicodedata

import pytest

from app import data
from app.csv_export import neutralise, quote, render_csv
from app.data import Report

HEADER = b"id,title,owner,rows\r\n"


def line_of(title: str, owner: str = "ops", rows: int = 1, rid: int = 1) -> str:
    """The data line of a one-row file (owner/rows/rid constants, title varies)."""
    body = render_csv([Report(rid, title, owner, rows)]).decode("utf-8")
    return body.split("\r\n")[1]


# --- C2: header and structure -------------------------------------------------


def test_header_line_exact_bytes():
    assert render_csv([]) == HEADER == b"id,title,owner,rows\r\n"
    assert len(HEADER) == 21


def test_empty_list_is_header_only_21_bytes():
    assert len(render_csv([])) == 21


def test_four_fields_per_row_including_hostile_cells():
    out = render_csv([Report(1, "a,b", 'he said "hi"\r\nnow', 5)])
    rows = list(csv.reader(io.StringIO(out.decode("utf-8")), strict=True))
    assert all(len(r) == 4 for r in rows)
    assert rows[1][2] == 'he said "hi"\r\nnow'  # parsed == stored, C4 fidelity


def test_row_order_is_order_given_emitter_never_resorts():
    body = render_csv([Report(4, "d", "o", 4), Report(1, "a", "o", 1)]).decode("utf-8")
    ids = [rec.split(",")[0] for rec in body.split("\r\n")[1:-1]]
    assert ids == ["4", "1"]


def test_repeated_render_is_byte_identical():
    reports = [Report(1, "=1+1", "ops", 12), Report(2, "plain, text", 'o"x', 0)]
    assert render_csv(reports) == render_csv(reports)


def test_crlf_only_as_record_terminator():
    body = render_csv([Report(1, "x", "y\r\nz", 2)])
    assert body.endswith(b"\r\n")
    assert b"\r" not in body.replace(b"\r\n", b"")
    assert b"\n" not in body.replace(b"\r\n", b"")


def test_restricted_is_never_a_column():
    assert render_csv([Report(3, "Payroll", "finance", 1, restricted=True)]) == (
        HEADER + b"3,Payroll,finance,1\r\n"
    )


# --- C2/C4: typing is per-column and value-blind -------------------------------


def test_rows_and_id_numeric_never_quoted_or_prefixed():
    assert line_of("t", rows=-42) == "1,t,ops,-42"  # bare negative, C2 typing
    assert line_of("t", rid=1) == "1,t,ops,1"


def test_text_lookalikes_are_text():
    assert line_of("-42") == "1,'-42,ops,1"  # text keeps the C4 predicate
    assert line_of("00123") == "1,00123,ops,1"  # verbatim, unquoted
    assert line_of("1E+3") == "1,1E+3,ops,1"  # lead "1" not in trigger set


# --- C4: worked examples, byte-exact --------------------------------------------


@pytest.mark.parametrize(
    ("stored", "rendered"),
    [
        ("hello", "hello"),  # byte-matrix row 1: v[0] not in T, verbatim
        ("=2+2", "'=2+2"),  # row 2: prefix only — a lead never forces quoting (rev 3 f2)
        ("-42", "'-42"),  # row 3: text column keeps the C4 predicate
        ("+1", "'+1"),  # row 5
        ("@SUM(A1)", "'@SUM(A1)"),  # row 6
        ("'=x", "''=x"),  # row 7: v[0]="'" ∈ T prefixes; 2nd ' is stored content
        ("'a", "''a"),  # rev 3 f1: apostrophe-lead is IN T = {=,+,-,@,']
        ("00123", "00123"),  # row 8: text, v[0] not in T → verbatim
        ("a, b", '"a, b"'),  # row 9: quoted ONLY for the comma, no prefix
        ("a, =b", '"a, =b"'),  # row 10: mid-field = is not a lead, not neutralised
        ('say "hi"', '"say ""hi"""'),  # row 11: inner " doubled inside the wrapper
        ("x\ry\r\nz\nw", '"x\ry\r\nz\nw"'),  # row 12: raw CR/LF only inside quotes
        ("1-1", "1-1"),  # v[0]="1" not in T verbatim
        (",", '","'),
        ('=a,"b"', '"\'=a,""b"""'),  # prefix inserted BEFORE quoting (C4)
        ("=1,2", "\"'=1,2\""),  # formula lead + comma: quoted and prefixed
        ("plain", "plain"),
        ("", ""),
        ("-", "'-"),  # sole trigger char still counts
        ("'", "''"),  # v[0]=T for the single apostrophe
        ("''", "'''"),  # prefix + two stored apostrophes
    ],
)
def test_c4_cell_examples(stored, rendered):
    # byte-exact: the serialized field, in place, in the full record
    assert render_csv([Report(1, stored, "ops", 1)]) == (
        HEADER + f"1,{rendered},ops,1".encode() + b"\r\n"
    )


TRIGGER_CORPUS = [
    "hello",
    "=2+2",
    "-42",
    "+1",
    "@SUM(A1)",
    "'=x",
    "'a",
    "00123",
    "a, b",
    "a, =b",
    'say "hi"',
    "x\ny",
    "'",
    "''",
    "=a,1",
    "'=a\tb",
    "@x=1+y-2",
    "=1\r\n2",
    "'a,b",
    "",
]
# every v with v[0] in T (and empty, and non-T) appears above; '-led, "+-led
# and @-led values inside quoted fields exercise prefix-inside-quotes.


@pytest.mark.parametrize("stored", TRIGGER_CORPUS)
def test_c4_fidelity_inverse_strips_exactly_one_leading_apostrophe(stored):
    """QA fidelity (rev 3 C4 ¶5): parse with stdlib csv, then strip exactly one
    leading ' iff present ⇒ == stored v, for every stored value incl. the
    apostrophe-led ones (f1)."""
    body = render_csv([Report(1, stored, "ops", 1)]).decode("utf-8")
    parsed = list(csv.reader(io.StringIO(body), strict=True))[1][1]
    stripped = parsed[1:] if parsed.startswith("'") else parsed
    assert stripped == stored


def test_parse_equals_apostrophe_plus_v_for_every_trigger_lead():
    for v in TRIGGER_CORPUS:
        if not v:
            continue
        body = render_csv([Report(1, v, "ops", 1)])
        parsed = list(csv.reader(io.StringIO(body.decode("utf-8")), strict=True))[1][1]
        if v[0] in ("=", "+", "-", "@", "'"):
            assert parsed == "'" + v  # rule == example == fidelity, one function
        else:
            assert parsed == v


def test_neutralise_and_quote_are_the_documented_pure_functions():
    assert neutralise("=x") == "'=x"
    assert neutralise("'=x") == "''=x"  # ' ∈ T (rev 3 f1): prefixed like any lead
    assert neutralise("''=x") == "'''=x"  # rule is purely v[0]-driven, no look-through
    assert neutralise("'a") == "''a"
    assert neutralise("x") == "x"
    assert neutralise("") == ""
    assert neutralise("'") == "''"
    assert quote("a,b") == '"a,b"'
    assert quote('a"b') == '"a""b"'
    assert quote("'=x") == "'=x"  # formula lead alone never forces quoting (C4)
    assert quote("ab") == "ab"


# --- C4: encoding fidelity ------------------------------------------------------


@pytest.mark.parametrize("form", ["NFC", "NFD"])
def test_unicode_normalisation_forms_round_trip_byte_exactly(form):
    title = unicodedata.normalize(form, "Ångström café ß")
    body = render_csv([Report(1, title, "o", 1)])
    assert title.encode("utf-8") in body  # stored bytes present untouched
    parsed = list(csv.reader(io.StringIO(body.decode("utf-8")), strict=True))[1][1]
    assert parsed == title


def test_emitter_never_truncates_32768_char_value():
    value = "x" * 32768
    body = render_csv([Report(1, value, "o", 1)])
    parsed = list(csv.reader(io.StringIO(body.decode("utf-8")), strict=True))[1]
    assert parsed[1] == value


# --- C6 Layer A: the seam ---------------------------------------------------------


def test_seeded_reports_fixture_replaces_served_data_without_restart(seeded_reports):
    seeded_reports([Report(1, "A", "a", 1), Report(2, "B", "b", 2, restricted=True)])
    assert [r.id for r in data.list_reports(data.ROLE_ADMIN)] == [1, 2]
    assert [r.id for r in data.list_reports(data.ROLE_VIEWER)] == [1]
    assert data.get_report(2, data.ROLE_VIEWER) is None
    assert data.get_report(2, data.ROLE_ADMIN) is not None


def test_seeded_reports_empty_set_yields_header_only_bytes(seeded_reports):
    seeded_reports([])
    assert data.list_reports(data.ROLE_ADMIN) == []
    assert render_csv(data.list_reports(data.ROLE_ADMIN)) == HEADER


def test_seam_entries_are_report_instances_so_typing_is_total(seeded_reports):
    seeded_reports([Report(id=5, title="=S", owner="o", rows=-9, restricted=False)])
    assert render_csv(data.list_reports(data.ROLE_VIEWER)) == HEADER + b"5,'=S,o,-9\r\n"


def test_teardown_restores_builtin_set(seeded_reports):
    seeded_reports([Report(99, "gone", "x", 0)])
    assert data.list_reports(data.ROLE_VIEWER)[0].id == 99


def test_builtin_set_after_teardown():
    # runs after the seeding test above: pytest keeps definition order, and the
    # fixture's monkeypatch teardown restores the module attribute per test.
    assert [r.id for r in data.list_reports(data.ROLE_ADMIN)] == [1, 2, 3, 4]
