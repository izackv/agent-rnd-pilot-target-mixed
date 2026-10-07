"""Shared fixtures — the C6 Layer A test seam (contract rev 3).

``seeded_reports`` replaces ``app.data._REPORTS`` through the module
attribute, so every read path that resolves the list at call time
(``data.list_reports`` / ``data.get_report``, and the export endpoint via
C3's verbatim reuse) serves the injected set with no restart. ``monkeypatch``
restores the built-in set at teardown. Empty permitted set = seed ``[]``.
"""

from __future__ import annotations

import pytest

from app import data


@pytest.fixture
def seeded_reports(monkeypatch):
    def seed(reports: list[data.Report]) -> None:
        monkeypatch.setattr(data, "_REPORTS", list(reports))

    return seed
