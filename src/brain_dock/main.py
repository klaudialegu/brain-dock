"""The web app: the core plus the enabled modules. Run with
`uv run uvicorn brain_dock.main:app --host 127.0.0.1`."""

from brain_dock import registry
from brain_dock.core.app import (  # noqa: F401  (re-exported for tests and tools)
    STATIC_DIR,
    TEMPLATES_DIR,
    DatabaseNotReadyError,
    create_app,
    invalid_request,
)
from brain_dock.core.web import get_session  # noqa: F401  (re-exported for tests)

app = create_app(registry.enabled())
