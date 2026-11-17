"""THREAT_MODEL.md names the tests that enforce each rule; a renamed or deleted test must
not leave the page pointing at nothing."""

import re

from brain_dock.core.db import REPO_ROOT

PAGE = REPO_ROOT / "THREAT_MODEL.md"
# `test_file.py::test_name` (under tests/ unless it starts with e2e/), then any number of
# `::test_other` that belong to the same file.
CITATION = re.compile(r"`((?:e2e/)?test_[a-z0-9_]+\.py)?::(test_[a-z0-9_]+)`")


def cited_tests() -> list[tuple[str, str]]:
    cited, current = [], None
    for path, name in CITATION.findall(PAGE.read_text()):
        current = path or current
        assert current, f"::{name} has no test file before it"
        cited.append((current, name))
    return cited


def test_threat_model_cites_tests_that_exist():
    cited = cited_tests()
    assert len(cited) >= 40  # the page cites its tests; a broken pattern would find none
    missing = []
    for path, name in cited:
        file = REPO_ROOT / (path if path.startswith("e2e/") else f"tests/{path}")
        if not file.exists() or not re.search(rf"^def {name}\(", file.read_text(), re.M):
            missing.append(f"{path}::{name}")
    assert missing == [], f"THREAT_MODEL.md cites tests that don't exist: {missing}"
