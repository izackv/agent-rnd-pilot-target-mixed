"""C6 Layer B seam: uvicorn-launchable app with launch-effective fixtures.

Launch as ``python -m uvicorn tests.e2e.fixture_app:app --port 8xxx`` from the
repo root (same cwd as ``tests/e2e/conftest.py``). If env var
``REPORTS_FIXTURE_FILE`` names a file, it must hold a JSON array of objects
with keys exactly ``{id,title,owner,rows,restricted}`` (``id``/``rows`` int and
not bool, ``title``/``owner`` str, ``restricted`` bool); ``app.data._REPORTS``
is replaced with ``Report`` instances at import time, before serving. Every
malformation — structural or type-level — raises during import and aborts
startup; never silent degradation. Unset env var ⇒ the built-in set, i.e. ≡
``app.main:app``.

Zero changes to ``app/`` are needed or allowed; production code never reads
this env var (seam purity, grep-asserted in tests/unit/test_seam_purity.py).
The launch contract itself is exercised by tests/integration/test_fixture_app_seam.py.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from app import data
from app.main import app

_KEYS = frozenset({"id", "title", "owner", "rows", "restricted"})


def _require_int(field: str, index: int, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"fixture entry {index}: '{field}' must be an int, got {value!r}")
    return value


def _require_str(field: str, index: int, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"fixture entry {index}: '{field}' must be a str, got {value!r}")
    return value


def _require_bool(field: str, index: int, value: object) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"fixture entry {index}: '{field}' must be a bool, got {value!r}")
    return value


def _validated_entry(index: int, entry: object) -> data.Report:
    if not isinstance(entry, Mapping):
        raise TypeError(f"fixture entry {index} must be an object, got {type(entry).__name__}")
    keys = set(entry)
    if keys != _KEYS:
        raise ValueError(
            f"fixture entry {index} keys must be exactly {sorted(_KEYS)}, "
            f"missing={sorted(_KEYS - keys)} extra={sorted(keys - _KEYS)}"
        )
    return data.Report(
        id=_require_int("id", index, entry["id"]),
        title=_require_str("title", index, entry["title"]),
        owner=_require_str("owner", index, entry["owner"]),
        rows=_require_int("rows", index, entry["rows"]),
        restricted=_require_bool("restricted", index, entry["restricted"]),
    )


def _load_fixture(path: str) -> list[data.Report]:
    with open(path, encoding="utf-8") as fh:
        entries = json.load(fh)
    if not isinstance(entries, list):
        raise TypeError(f"fixture root must be a JSON array, got {type(entries).__name__}")
    return [_validated_entry(i, e) for i, e in enumerate(entries)]


_fixture_file = os.environ.get("REPORTS_FIXTURE_FILE")
if _fixture_file:
    data._REPORTS = _load_fixture(_fixture_file)

__all__ = ["app"]
