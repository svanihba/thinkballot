"""Shared plumbing: how services call each other over HTTP, and how each service app is built."""

import hmac
import logging
import socket
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection
from urllib3.connectionpool import HTTPConnectionPool

from flask import Flask, abort, jsonify, request
from werkzeug.exceptions import HTTPException

from . import config

log = logging.getLogger("thinkballot")


class ServiceError(Exception):
    """Another service could not be reached or returned an error."""

    def __init__(self, service, message, status=502):
        super().__init__(f"{service}: {message}")
        self.detail = message
        self.service = service
        self.status = status


class _UnixConnection(HTTPConnection):
    def __init__(self, socket_path, *args, **kwargs):
        super().__init__("localhost", *args, **kwargs)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout if isinstance(self.timeout, (int, float)) else None)
        self.sock.connect(self.socket_path)


class _UnixPool(HTTPConnectionPool):
    def __init__(self, socket_path, **kwargs):
        super().__init__("localhost", **kwargs)
        self.socket_path = socket_path

    def _new_conn(self):
        return _UnixConnection(self.socket_path, timeout=self.timeout.connect_timeout)


class _UnixAdapter(HTTPAdapter):
    """Sends plain HTTP over a unix socket (the server binds one instead of a TCP port)."""

    def __init__(self, socket_path):
        super().__init__()
        self.pool = _UnixPool(socket_path, maxsize=16)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        return self.pool

    def request_url(self, request, proxies):
        return request.path_url


# The whole ThinkBallot WSGI app, registered by thinkballot.app.create_app for "inproc" calls.
_inproc_app = None


def register_inproc_app(app):
    global _inproc_app
    _inproc_app = app


class _InprocResponse:
    def __init__(self, resp):
        self.status_code = resp.status_code
        self.headers = resp.headers
        self._resp = resp

    def json(self):
        return self._resp.get_json()


class _InprocSession:
    """Hands each HTTP request straight to this process's WSGI app: same API, same status codes,
    but no socket round trip, so a request never waits for a second worker thread."""

    def request(self, method, url, timeout=None, headers=None, params=None, json=None):
        from werkzeug.test import Client
        if _inproc_app is None:
            raise requests.ConnectionError("in-process app not registered")
        params = {k: v for k, v in (params or {}).items() if v is not None}
        resp = Client(_inproc_app).open(url, method=method, headers=headers, query_string=params, json=json)
        return _InprocResponse(resp)


def _session_for(base_url):
    """(session, http base url). "unix:/run/x.sock/svc/ballot" -> requests over that socket."""
    if base_url.startswith("inproc"):
        return _InprocSession(), base_url[len("inproc"):]
    session = requests.Session()
    if base_url.startswith("unix:"):
        path = base_url[len("unix:"):]
        sock, _, rest = path.partition(".sock")
        session.mount("http://localhost", _UnixAdapter(sock + ".sock"))
        return session, "http://localhost" + rest
    return session, base_url


class ServiceClient:
    """Calls one service's JSON API by HTTP. Logs one line per call (path and timing, never bodies)."""

    def __init__(self, name, base_url=None, timeout=None):
        self.name = name
        self.session, self.base_url = _session_for((base_url or config.SERVICE_URLS[name]).rstrip("/"))
        self.timeout = timeout or config.SERVICE_TIMEOUT_SECONDS

    def get(self, path, **params):
        return self._call("GET", path, params=params)

    def post(self, path, payload):
        return self._call("POST", path, json=payload)

    def _call(self, method, path, **kwargs):
        url = self.base_url + path
        started = time.monotonic()
        headers = {"X-TB-Internal": config.INTERNAL_TOKEN}
        try:
            resp = self.session.request(method, url, timeout=self.timeout, headers=headers, **kwargs)
        except requests.RequestException as exc:
            log.warning("svc %s %s %s failed: %s", self.name, method, path, type(exc).__name__)
            raise ServiceError(self.name, "unreachable") from exc
        log.info("svc %s %s %s -> %s in %.0f ms", self.name, method, path, resp.status_code,
                 (time.monotonic() - started) * 1000)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
            detail = body.get("detail") if isinstance(body, dict) else None
            raise ServiceError(self.name, detail or f"HTTP {resp.status_code}", resp.status_code)
        return resp.json()


def make_service(name, internal=False):
    """A Flask app for one JSON service, with errors always returned as JSON.

    internal=True: only other ThinkBallot services may call it (shared token), because it spends AI
    credits or acts on behalf of signed-in users.
    """
    app = Flask(f"thinkballot.{name}")

    if internal:
        @app.before_request
        def require_internal_token():
            if request.path == "/health":
                return None
            sent = request.headers.get("X-TB-Internal", "")
            if not hmac.compare_digest(sent, config.INTERNAL_TOKEN):
                abort(403, "internal service")
            return None

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.name, detail=exc.description), exc.code

    @app.get("/health")
    def health():
        return jsonify(service=name, ok=True)

    return app
