import inspect

from brain_dock.core.app import api_routes
from brain_dock.main import app


def test_post_routes_are_plain_functions():
    # FastAPI runs plain `def` routes in worker threads, so their (synchronous) database
    # calls never block the event loop. The form is read by an async dependency instead.
    post_routes = [r for r in api_routes(app) if "POST" in r.methods]

    assert post_routes  # the check covers real routes
    for route in post_routes:
        assert not inspect.iscoroutinefunction(route.endpoint), route.path
