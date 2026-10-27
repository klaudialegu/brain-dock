"""The contract every module must pass (ADR 0007). Parametrized over installed modules,
so a new module is checked the moment it's added to the registry."""

import ast
import inspect
from pathlib import Path

import pytest
from sqlmodel import SQLModel

from brain_dock import registry
from brain_dock.core.agents.tools import tool_policy_problems
from brain_dock.core.modules import Manifest, NavEntry
from brain_dock.core.security import verify_csrf

MODULES = registry.installed()
MODULES_DIR = Path(registry.__file__).parent / "modules"


def package_dir(m: Manifest) -> Path:
    return MODULES_DIR / m.name


def table_classes():
    """Every table model class, found through SQLModel's subclasses."""
    seen, todo = [], list(SQLModel.__subclasses__())
    while todo:
        cls = todo.pop()
        todo.extend(cls.__subclasses__())
        if getattr(cls, "__table__", None) is not None:
            seen.append(cls)
    return seen


@pytest.mark.parametrize("m", MODULES, ids=lambda m: m.name)
def test_manifest_is_complete(m):
    assert package_dir(m).is_dir(), "the name must match the package folder"
    assert m.description.strip()
    assert any(m.home.startswith(p) for p in m.paths), "home must be one of its own paths"
    assert m.nav and all(isinstance(e, NavEntry) for e in m.nav)
    assert all(any(e.path.startswith(p) for p in m.paths) for e in m.nav)
    assert m.templates.is_dir()
    assert m.static is None or m.static.is_dir()
    assert all(isinstance(p, str) for p in m.permissions)


@pytest.mark.parametrize("m", MODULES, ids=lambda m: m.name)
def test_routes_stay_in_declared_paths(m):
    routes = list(m.router.routes)

    assert routes  # the check covers real routes
    for route in routes:
        assert any(route.path.startswith(p) for p in m.paths), route.path


@pytest.mark.parametrize("m", MODULES, ids=lambda m: m.name)
def test_post_routes_check_csrf(m):
    post_routes = [r for r in m.router.routes if "POST" in r.methods]

    for route in post_routes:
        assert verify_csrf in [d.call for d in route.dependant.dependencies], route.path
        assert not inspect.iscoroutinefunction(route.endpoint), route.path


@pytest.mark.parametrize("m", MODULES, ids=lambda m: m.name)
def test_tables_match_the_manifest_and_are_prefixed(m):
    package = f"brain_dock.modules.{m.name}"
    defined = {c.__table__.name for c in table_classes() if c.__module__.startswith(package)}

    assert defined == set(m.tables), "the manifest must list exactly the tables it defines"
    for table in m.tables:
        # ADR 0007: new modules prefix their tables; legacy names are the one exception.
        assert table.startswith(f"{m.name}_") or table in m.legacy_table_names, table
    # The exception only covers names that really exist, so it can't grow silently.
    assert set(m.legacy_table_names) <= set(m.tables)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


@pytest.mark.parametrize("m", MODULES, ids=lambda m: m.name)
def test_imports_no_other_module(m):
    files = sorted(package_dir(m).rglob("*.py"))
    own = f"brain_dock.modules.{m.name}"

    assert files  # the scan covers real files
    for path in files:
        for name in imported_modules(path):
            if name.startswith("brain_dock.modules.") and name != "brain_dock.modules":
                assert name == own or name.startswith(own + "."), f"{path.name} imports {name}"
            assert not name.startswith(("brain_dock.registry", "brain_dock.main")), path.name


def alembic_scripts():
    from alembic.script import ScriptDirectory

    from brain_dock.core.db import _alembic_config

    return ScriptDirectory.from_config(_alembic_config())


@pytest.mark.parametrize("m", MODULES, ids=lambda m: m.name)
def test_migrations_are_a_branch_of_their_own(m):
    import configparser

    from brain_dock.core.db import ALEMBIC_INI

    assert m.migrations.is_dir()
    scripts = alembic_scripts()
    own = [s for s in scripts.walk_revisions() if Path(s.path).parent == m.migrations]

    assert own  # the module really has migrations
    by_id = {s.revision: s for s in own}
    for script in own:
        if script.down_revision is None:
            assert m.name in script.branch_labels, f"{script.revision} must start the branch"
        else:
            # Its history stays inside this module's folder: no revision built on another's.
            parents = script.down_revision
            for parent in parents if isinstance(parents, tuple) else (parents,):
                assert parent in by_id, f"{script.revision} builds on {parent} from elsewhere"

    # alembic.ini is the list of installed migration folders, so the CLI sees them too.
    ini = configparser.ConfigParser()
    ini.read(ALEMBIC_INI)
    listed = {
        Path(p.replace("%(here)s", str(ALEMBIC_INI.parent))).resolve()
        for p in ini.get("alembic", "version_locations", raw=True).split()
    }
    assert m.migrations.resolve() in listed


@pytest.mark.parametrize("m", MODULES, ids=lambda m: m.name)
def test_migrations_match_the_models(m):
    from alembic import command
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import MetaData
    from sqlalchemy.pool import StaticPool

    from brain_dock.core.db import _alembic_config, get_engine

    module_metadata = MetaData()
    for table in m.tables:
        SQLModel.metadata.tables[table].to_metadata(module_metadata)

    engine = get_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as connection:
        command.upgrade(_alembic_config(connection), f"{m.name}@head")
        diff = compare_metadata(MigrationContext.configure(connection), module_metadata)
    engine.dispose()

    assert diff == [], "a model changed without a migration in this module"


@pytest.mark.parametrize("m", MODULES, ids=lambda m: m.name)
def test_agent_tools_follow_the_policy(m):
    # ADR 0008: no tool may send data out or delete anything without an Accepted ADR.
    assert tool_policy_problems(m.name, m.agent_tools) == []
