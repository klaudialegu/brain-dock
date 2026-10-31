"""Which modules are installed, and which are enabled. The only place that imports modules
(ADR 0007): the core gets manifests from here, never by importing a module itself."""

import os
from collections.abc import Mapping

from brain_dock.core.modules import Manifest
from brain_dock.modules.inbox.manifest import manifest as inbox
from brain_dock.modules.job_search.manifest import manifest as job_search

INSTALLED: dict[str, Manifest] = {m.name: m for m in [job_search, inbox]}


class UnknownModuleError(ValueError):
    """BRAIN_DOCK_MODULES names a module that isn't installed. The app doesn't start."""


def installed() -> list[Manifest]:
    return list(INSTALLED.values())


def enabled(environ: Mapping[str, str] = os.environ) -> list[Manifest]:
    """BRAIN_DOCK_MODULES picks the enabled modules (comma-separated, in nav order); unset
    means all installed, empty means none. Disabling never touches a module's data."""
    raw = environ.get("BRAIN_DOCK_MODULES")
    if raw is None:
        return installed()
    names = [n.strip() for n in raw.split(",") if n.strip()]
    unknown = [n for n in names if n not in INSTALLED]
    if unknown:
        raise UnknownModuleError(
            f"BRAIN_DOCK_MODULES names unknown module(s): {', '.join(unknown)}. "
            f"Installed modules: {', '.join(INSTALLED) or '(none)'}."
        )
    return [INSTALLED[n] for n in dict.fromkeys(names)]
