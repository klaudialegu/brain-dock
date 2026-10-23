"""Which modules are installed, and which are enabled. The only place that imports modules
(ADR 0007): the core gets manifests from here, never by importing a module itself."""

from brain_dock.core.modules import Manifest
from brain_dock.modules.job_search.manifest import manifest as job_search

INSTALLED: dict[str, Manifest] = {m.name: m for m in [job_search]}


def installed() -> list[Manifest]:
    return list(INSTALLED.values())


def enabled() -> list[Manifest]:
    return installed()
