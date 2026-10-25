"""Test setup: offline AI stub, a temporary database, and the whole app on a real local port."""

import importlib
import json
import logging
import threading

import pytest
from werkzeug.serving import make_server

from thinkballot import config


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    """Run all five services in one process on a free port, as in production, with dummy data."""
    tmp = tmp_path_factory.mktemp("tb")
    config.AI_PROVIDER = "stub"
    config.DB_PATH = tmp / "test.sqlite3"
    config.COMMUNITY_DB_PATH = tmp / "community.sqlite3"
    config.RATE_DB_PATH = tmp / "ratelimit.sqlite3"
    srv = make_server("127.0.0.1", 0, lambda e, s: app(e, s), threaded=True)
    base = f"http://127.0.0.1:{srv.server_port}"
    config.PUBLIC_BASE = base
    config.SERVICE_URLS.update({n: f"{base}/svc/{n}" for n in config.SERVICE_URLS})

    from thinkballot.services.ballot import db
    data = json.loads((config.ROOT / "data" / "dummy" / "measures.json").read_text())
    db.replace_all(db.connect(), data["election"], data["measures"])

    app_module = importlib.import_module("thinkballot.app")
    app = app_module.create_app()
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield base
    srv.shutdown()
