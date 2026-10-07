"""C6 Layer B seam: uvicorn-launchable app with launch-effective fixtures.

Launch as ``python -m uvicorn tests.e2e.fixture_app:app --port 8xxx`` from the
repo root (same cwd as ``tests/e2e/conftest.py``). If env var
``REPORTS_FIXTURE_FILE`` names a file, it must hold a JSON array of objects
with keys exactly ``{id,title,owner,rows,restricted}`` (``id``/``rows`` int,
``title``/``owner`` str, ``restricted`` bool); ``app.data._REPORTS`` is
replaced with ``Report`` instances at import time, before serving. Any
malformation raises during import and aborts startup — never silent
degradation. Unset env var ⇒ the built-in set, i.e. ≡ ``app.main:app``.

Zero changes to ``app/`` are needed or allowed; production code never reads
this env var (seam purity, grep-asserted in tests/unit/test_seam_purity.py).
"""

from __future__ import annotations

import json
import os

from app import data
from app.main import app

_fixture_file = os.environ.get("REPORTS_FIXTURE_FILE")
if _fixture_file:
    with open(_fixture_file, encoding="utf-8") as fh:
        _entries = json.load(fh)
    data._REPORTS = [data.Report(**entry) for entry in _entries]

__all__ = ["app"]
