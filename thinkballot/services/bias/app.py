"""bias service: the Bias Buster Engine's JSON API."""

import json

from flask import abort, jsonify, request

from ... import config
from ...servicekit import make_service
from . import engine

REPORT_PATH = config.REPORT_PATH

MODES = {"verify", "audit", "enforce", "wording"}


def _sources(body):
    sources = body.get("sources")
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        abort(400, "sources must be a list of official text passages")
    return sources


def create_app():
    app = make_service("bias", internal=True)

    @app.post("/check/answer")
    def check_answer():
        """Enforce mode for an AI answer: {points: [{claim, quote}], sources: [...], ai_review: bool}."""
        body = request.get_json(silent=True) or {}
        points = body.get("points")
        if not isinstance(points, list):
            abort(400, "points must be a list")
        points = [p for p in points if isinstance(p, dict)]
        return jsonify(engine.check_answer(points, _sources(body), use_ai=body.get("ai_review", True)))

    @app.post("/check/text")
    def check_text():
        """{text, sources, mode: verify|audit|enforce, sides?: {yes, no}}."""
        body = request.get_json(silent=True) or {}
        mode = body.get("mode")
        if mode not in MODES:
            abort(400, "mode must be verify, audit or enforce")
        text = body.get("text")
        if not isinstance(text, str):
            abort(400, "text is required")
        return jsonify(engine.check_text(text, _sources(body), mode, body.get("sides")))

    @app.get("/report")
    def report():
        """Summary of the latest seed run (written by scripts/seed.py)."""
        if not REPORT_PATH.exists():
            abort(404, "No report yet.")
        return jsonify(json.loads(REPORT_PATH.read_text())["summary"])

    return app
