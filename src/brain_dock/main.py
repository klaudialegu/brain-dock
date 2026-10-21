from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from brain_dock import db
from brain_dock.clocks import load_cities, world_clocks
from brain_dock.db import get_engine, is_at_head
from brain_dock.queries import list_applications

TEMPLATES_DIR = Path(__file__).parent / "templates"
# Local, gitignored settings at the repo root. See config.example.toml for the format.
CONFIG_PATH = Path(__file__).parents[2] / "config.toml"


class DatabaseNotReadyError(RuntimeError):
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Never migrates on its own: changing the only copy of the data should be a choice.
    # Reads db.DB_PATH at startup time, so tests can point it at a temp file.
    if not db.DB_PATH.exists():
        raise DatabaseNotReadyError("No database yet. Run: uv run python -m brain_dock.db")
    engine = get_engine()
    if not is_at_head(engine):
        engine.dispose()
        raise DatabaseNotReadyError(
            "The database needs migrating. Run: uv run python -m brain_dock.db"
        )
    app.state.engine = engine
    yield
    engine.dispose()


app = FastAPI(title="Brain Dock", lifespan=lifespan)
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def get_session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    cities = load_cities(CONFIG_PATH)
    context = {"clocks": world_clocks(cities=cities), "reference_tz": cities[0][1]}
    return templates.TemplateResponse(request, "index.html", context)


@app.get("/applications", response_class=HTMLResponse)
def applications(request: Request, session: SessionDep) -> HTMLResponse:
    context = {"applications": list_applications(session)}
    return templates.TemplateResponse(request, "applications.html", context)
