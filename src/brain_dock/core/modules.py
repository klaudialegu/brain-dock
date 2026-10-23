"""What a module is: a manifest the core reads (ADR 0007). Modules import this; the core
never imports a module."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter


@dataclass(frozen=True)
class NavEntry:
    label: str
    path: str


@dataclass(frozen=True)
class Manifest:
    name: str  # also the package name under brain_dock/modules/ and the template prefix
    description: str
    home: str  # where "/" goes when this is the first enabled module
    router: APIRouter
    paths: tuple[str, ...]  # URL prefixes every route of this module stays under
    nav: tuple[NavEntry, ...]
    tables: tuple[str, ...]  # tables this module owns
    migrations: Path  # this module's Alembic versions folder (its own branch)
    templates: Path  # loaded as "<name>/<file>", so names can't clash across modules
    static: Path | None = None  # served at /static/modules/<name>/
    stylesheets: tuple[str, ...] = ()  # extra stylesheet URLs for every page
    template_globals: dict[str, Callable] = field(default_factory=dict)
    permissions: tuple[str, ...] = ()  # core services it uses; enforced once they exist
    jobs: tuple = ()  # scheduled jobs; none until the scheduler exists
    mcp_tools: tuple = ()  # later
    # Documented exception (ADR 0007): table names allowed without the module-name prefix.
    legacy_table_names: tuple[str, ...] = ()
