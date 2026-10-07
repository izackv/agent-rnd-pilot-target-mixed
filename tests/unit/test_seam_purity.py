"""C6 seam purity — grep assertions.

``REPORTS_FIXTURE_FILE`` may exist only under ``tests/`` (no production
parameter, header, env flag or endpoint may swap ``_REPORTS``), and no module
may name-bind ``_REPORTS`` (that would detach the Layer A seam).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}


def _source_files() -> list[Path]:
    return [
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS)
        and p.suffix in {".py", ".html", ".js", ".md", ".toml", ".yaml", ".yml"}
    ]


def test_fixture_env_var_lives_only_under_tests():
    hits = [p for p in _source_files() if "REPORTS_FIXTURE_FILE" in p.read_text()]
    assert hits, "fixture seam is not wired at all"
    for path in hits:
        parts = path.relative_to(ROOT).parts
        assert parts[0] == "tests", f"seam env var leaked into {path}"


def test_no_module_name_binds_reports_list():
    pattern = re.compile(r"from\s+app\.data\s+import\s+.*\b_REPORTS\b")
    offenders = [p for p in _source_files() if p.suffix == ".py" and pattern.search(p.read_text())]
    assert offenders == [], f"_REPORTS name-bound in {offenders}"


def test_production_code_has_no_data_switching_route():
    main_src = (ROOT / "app" / "main.py").read_text()
    assert "fixture" not in main_src.lower()
    assert "_REPORTS" not in main_src  # only via data.list_reports at call time (C3)
