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


def test_registry_lists_installed_and_enabled_modules():
    from brain_dock import registry

    names = [m.name for m in registry.installed()]

    assert "job_search" in names
    assert [m.name for m in registry.enabled({})] == names  # unset: all installed
    assert registry.enabled({"BRAIN_DOCK_MODULES": ""}) == []  # empty: none
    assert [m.name for m in registry.enabled({"BRAIN_DOCK_MODULES": " job_search , "})] == [
        "job_search"
    ]


def test_unknown_module_name_stops_startup(tmp_path):
    import os
    import subprocess
    import sys

    import pytest

    from brain_dock import registry

    with pytest.raises(registry.UnknownModuleError) as caught:
        registry.enabled({"BRAIN_DOCK_MODULES": "job_search,jobsearch"})
    assert "unknown module(s): jobsearch" in str(caught.value)
    assert "Installed modules: job_search" in str(caught.value)

    # And the real app refuses to start: importing it fails with that message.
    env = dict(os.environ, BRAIN_DOCK_MODULES="jobsearch", BRAIN_DOCK_DB=str(tmp_path / "x.db"))
    result = subprocess.run(
        [sys.executable, "-c", "import brain_dock.main"], env=env, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert "UnknownModuleError" in result.stderr
    assert "unknown module(s): jobsearch" in result.stderr
    assert not (tmp_path / "x.db").exists()  # it stopped before touching any database
