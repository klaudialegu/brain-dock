from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from brain_dock.clocks import load_cities, world_clocks

TEMPLATES_DIR = Path(__file__).parent / "templates"
# Local, gitignored settings at the repo root. See config.example.toml for the format.
CONFIG_PATH = Path(__file__).parents[2] / "config.toml"

app = FastAPI(title="Brain Dock")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    cities = load_cities(CONFIG_PATH)
    context = {"clocks": world_clocks(cities=cities), "reference_tz": cities[0][1]}
    return templates.TemplateResponse(request, "index.html", context)
