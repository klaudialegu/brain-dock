"""Kill switches (ADR 0007, 0008): files next to the database that stop agents.

`touch data/agents-off` stops every agent; `touch data/agents-off-<module>` stops one
module's. They're checked before every tool call (and every model call), so they work
mid-run without a restart. Delete the file to turn agents back on.
"""

from pathlib import Path

GLOBAL_SWITCH = "agents-off"


def switch_paths(folder: Path, module: str) -> tuple[Path, Path]:
    return folder / GLOBAL_SWITCH, folder / f"{GLOBAL_SWITCH}-{module}"


def agents_allowed(folder: Path, module: str) -> bool:
    """False when a switch is set, and also when checking fails: fail closed."""
    try:
        return not any(path.exists() for path in switch_paths(folder, module))
    except Exception:
        return False
