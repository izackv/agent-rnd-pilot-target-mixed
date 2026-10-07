"""LOCAL STUB for GET /api/reports/export — contract rev 3 (MIX-9/MIX-17), test-only.

The backend endpoint ships on MIX-12 and is not on this branch's base. MIX-13's e2e parity
tests (J1/J2) launch this stub instead of a bare ``app.main`` so the UI control can be
verified before the backend merges. It reuses ``main._role`` and ``data.list_reports`` by
import (C3's single path), serves bytes per C1/C2/C4/C5/C7, and honours the C6-B
``REPORTS_FIXTURE_FILE`` launch seam exactly as the contract describes it. When MIX-12
merges, the integration milestone retargets these tests to the real endpoint and this file
comes out with the stub.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from fastapi import Header, Response

from app import data
from app.main import _role, app

# C4 ¶5: formula-lead trigger set (rev 3: includes the apostrophe).
_TRIGGERS = ("=", "+", "-", "@", "'")


def _serialize_text(value: str) -> str:
    """Neutralise (C4 ¶5), then RFC 4180 minimal-quote (C4 ¶1). Quoting only for , \" CR LF."""
    cell = "'" + value if value and value[0] in _TRIGGERS else value
    if any(ch in cell for ch in (",", '"', "\r", "\n")):
        return '"' + cell.replace('"', '""') + '"'
    return cell


def csv_bytes(reports: list[data.Report]) -> bytes:
    lines = ["id,title,owner,rows"]  # C2 header, exact spelling
    lines += [
        f"{r.id},{_serialize_text(r.title)},{_serialize_text(r.owner)},{r.rows}"
        for r in sorted(reports, key=lambda r: r.id)
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")  # CRLF on every record incl. last


@app.get("/api/reports/export")
def export(x_role: str | None = Header(default=None)) -> Response:
    body = csv_bytes(data.list_reports(_role(x_role)))  # C3: role path reused verbatim
    date = datetime.now(UTC).date().strftime("%Y-%m-%d")
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="reports-{date}.csv"'},
    )


# C1 routing: the static path must be matched before the dynamic int route; the decorated
# registration lands at the tail, so move it in front of /api/reports/{report_id}.
_routes = app.router.routes
_export_route = _routes.pop()
_paths = [getattr(r, "path", None) for r in _routes]
_dyn = _paths.index("/api/reports/{report_id}")
_routes.insert(_dyn, _export_route)

# C6-B Layer B seam: launch-time data injection; unset means the built-in set (≡ app.main).
_fixture_file = os.environ.get("REPORTS_FIXTURE_FILE")
if _fixture_file:
    with open(_fixture_file, encoding="utf-8") as fh:
        data._REPORTS = [data.Report(**entry) for entry in json.load(fh)]
