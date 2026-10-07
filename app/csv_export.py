"""CSV emitter for the report export (contract rev 3, clauses C2 and C4).

Pure serialization over already-permission-filtered ``Report`` instances:
this module never filters, re-sorts or truncates. Permission filtering is
C3's job (``main._role`` + ``data.list_reports``, reused verbatim by the
endpoint in ``app/main.py``); keeping it out of here is what makes the
emitter independently testable against the C2/C4 examples.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.data import Report

HEADER_FIELDS = ("id", "title", "owner", "rows")
_CRLF = "\r\n"
_QUOTE_NEEDLES = (",", '"', "\r", "\n")
# OD-7=B formula-lead trigger set T, normative per contract rev 3 C4 ¶5.
_FORMULA_LEAD = ("=", "+", "-", "@", "'")
_APOSTROPHE = "'"  # U+0027 documented neutralisation prefix


def neutralise(value: str) -> str:
    """C4 (OD-7=B, rev 3): a non-empty stored *text* cell whose first
    character is in T = {``=``, ``+``, ``-``, ``@``, ``'``} serialises as
    ``'`` + value, inserted *before* RFC 4180 quoting; otherwise verbatim.

    Only v[0] decides — a lead never forces quoting and later trigger chars
    are not neutralised (matrix doc ``c4-byte-matrix``). A value already
    starting with the documented prefix is prefixed too (``'=x`` → ``''=x``;
    the second ``'`` is stored content, not escaping), which makes the QA
    fidelity inverse "strip exactly one leading apostrophe iff present"
    exactly invert this function for every stored v. Numeric columns never
    call this (C2 typing).
    """
    if value and value[0] in _FORMULA_LEAD:
        return _APOSTROPHE + value
    return value


def quote(field: str) -> str:
    """RFC 4180 minimal quoting: wrap fields containing ``,`` ``"`` CR or LF
    in double quotes, doubling inner ``"``. A formula lead alone never forces
    quoting (C4)."""
    if any(ch in field for ch in _QUOTE_NEEDLES):
        return '"' + field.replace('"', '""') + '"'
    return field


def render_csv(reports: Iterable[Report]) -> bytes:
    """Serialise reports to one CSV document.

    - Header line is the 19 bytes ``id,title,owner,rows`` (C2); ``restricted``
      is never a column — it is filtered by permission in C3, not emitted.
    - Every record, including the last, is terminated by CRLF.
    - Row order is the order given (``list_reports`` output, id-ascending for
      application data); the emitter never re-sorts, so parity with
      ``GET /api/reports`` holds for any injected set (C3).
    - ``id``/``rows`` render as ``str(int)``: never quoted, never prefixed.
      ``title``/``owner`` are text: neutralise, then quote (C2 value-blind).
    - Strict UTF-8, no Unicode normalisation, no BOM. The BOM belongs to the
      browser download path only (C4); API-path bytes are pure UTF-8.
    """
    lines = [",".join(HEADER_FIELDS)]
    for r in reports:
        lines.append(
            ",".join(
                [
                    str(r.id),
                    quote(neutralise(r.title)),
                    quote(neutralise(r.owner)),
                    str(r.rows),
                ]
            )
        )
    return (_CRLF.join(lines) + _CRLF).encode("utf-8", "strict")
