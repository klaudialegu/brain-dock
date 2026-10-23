"""ADR 0007: the core never imports a module, the registry, or the app that composes them."""

from pathlib import Path

from brain_dock.core import app as core_app

from .test_module_contract import imported_modules

CORE_DIR = Path(core_app.__file__).parent


def test_core_never_imports_a_module():
    files = sorted(CORE_DIR.rglob("*.py"))

    assert len(files) >= 5  # the scan covers the real core files
    for path in files:
        for name in imported_modules(path):
            assert not name.startswith(
                ("brain_dock.modules", "brain_dock.registry", "brain_dock.main")
            ), f"core/{path.name} imports {name}"
