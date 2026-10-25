"""Shared plumbing: how services call each other over HTTP, and how each service app is built."""

import hmac
import logging
import time

import requests

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


class ServiceClient:
    """Calls one service's JSON API by HTTP. Logs one line per call (path and timing, never bodies)."""

    def __init__(self, name, base_url=None, timeout=None):
        self.name = name
        self.base_url = (base_url or config.SERVICE_URLS[name]).rstrip("/")
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
            resp = requests.request(method, url, timeout=self.timeout, headers=headers, **kwargs)
        except requests.RequestException as exc:
            log.warning("svc %s %s %s failed: %s", self.name, method, path, type(exc).__name__)
            raise ServiceError(self.name, "unreachable") from exc
        log.info("svc %s %s %s -> %s in %.0f ms", self.name, method, path, resp.status_code,
                 (time.monotonic() - started) * 1000)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            detail = resp.json().get("detail") if resp.headers.get("content-type", "").startswith(
                "application/json") else None
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
