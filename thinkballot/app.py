"""Builds the whole ThinkBallot process: eight services, each mounted under its own path.

The services only talk to each other over HTTP, so any of them can move to its own process later
by changing its URL in config.
"""

import logging

from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.middleware.proxy_fix import ProxyFix

from .services.ask.app import create_app as ask_app
from .services.ballot.app import create_app as ballot_app
from .services.bias.app import create_app as bias_app
from .services.community.app import create_app as community_app
from .services.geo.app import create_app as geo_app
from .services.results.app import create_app as results_app
from .services.search.app import create_app as search_app
from .services.web.app import create_app as web_app
from .servicekit import register_inproc_app


def create_app():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    # Werkzeug's own access log prints full URLs; keep it quiet so nothing personal is logged.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    services = DispatcherMiddleware(web_app(), {
        "/svc/ballot": ballot_app(),
        "/svc/geo": geo_app(),
        "/svc/ask": ask_app(),
        "/svc/bias": bias_app(),
        "/svc/search": search_app(),
        "/svc/community": community_app(),
        "/svc/results": results_app(),
    })
    register_inproc_app(services)  # for TB_INTERNAL_URL=inproc
    return ProxyFix(services, x_for=1, x_proto=1, x_host=1)  # trust one proxy: Caddy
