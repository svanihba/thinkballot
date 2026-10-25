"""Shared plumbing: how services call each other over HTTP, and how each service app is built."""

import logging
import time

import requests
from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from . import config

log = logging.getLogger("thinkballot")


class ServiceError(Exception):
    """Another service could not be reached or returned an error."""

    def __init__(self, service, message, status=502):
        super().__init__(f"{service}: {message}")
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
        try:
            resp = requests.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            log.warning("svc %s %s %s failed: %s", self.name, method, path, type(exc).__name__)
            raise ServiceError(self.name, "unreachable") from exc
        log.info("svc %s %s %s -> %s in %.0f ms", self.name, method, path, resp.status_code,
                 (time.monotonic() - started) * 1000)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise ServiceError(self.name, f"HTTP {resp.status_code}", resp.status_code)
        return resp.json()


def make_service(name):
    """A Flask app for one JSON service, with errors always returned as JSON."""
    app = Flask(f"thinkballot.{name}")

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.name, detail=exc.description), exc.code

    @app.get("/health")
    def health():
        return jsonify(service=name, ok=True)

    return app
