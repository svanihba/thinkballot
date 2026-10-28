"""Answers to the suggested questions, prepared in advance: stored, re-checked, and never for typed questions."""

import importlib.util
import itertools
import json
import logging
from datetime import datetime, timezone

import pytest
import requests

from thinkballot import ai, config
from thinkballot.services.ask import app as ask_app
from thinkballot.services.ask import cache
from thinkballot.services.ballot import db
from thinkballot.services.bias import engine
from thinkballot.servicekit import ServiceClient
from thinkballot.suggested import SUGGESTED_QUESTIONS

QUESTION = SUGGESTED_QUESTIONS[0]
_clients = itertools.count(1)


def ask(server, question, measure_id="prop-a"):
    """Straight to the ask service, each time as a new client, so the per-client limit never interferes."""
    body = {"measure_id": measure_id, "question": question, "client": f"10.9.{next(_clients)}.1"}
    return requests.post(server + "/svc/ask/ask", json=body,
                         headers={"X-TB-Internal": config.INTERNAL_TOKEN}).json()


def rows():
    with cache._connect() as conn:
        return conn.execute("SELECT measure_id, result FROM answer").fetchall()


@pytest.fixture(autouse=True)
def empty_cache(server):
    with cache._connect() as conn:
        conn.execute("DELETE FROM answer")


def test_suggested_question_is_prepared_then_served_from_cache(server):
    first = ask(server, QUESTION)
    assert first["status"] == "answered" and "prepared" not in first
    second = ask(server, QUESTION)
    assert second["prepared"] == datetime.now(timezone.utc).date().isoformat()
    assert second["status"] == "answered" and second["verdict"] == first["verdict"]
    assert second["points"] == first["points"]  # with the field and link attached again


def test_typed_question_is_never_stored(server):
    typed = "What would change if this passes"  # one character away from a suggested question
    assert ask(server, typed)["status"] == "answered"
    assert ask(server, "  " + QUESTION + "  ")["status"] == "answered"  # trimmed: this one is suggested
    assert [r[0] for r in rows()] == ["prop-a"]
    assert typed.encode() not in config.ASK_CACHE_PATH.read_bytes()


def test_blocked_answer_is_not_stored(server, monkeypatch):
    bad = {"refused": False, "points": [{"claim": "It makes things better.", "quote": "not in the official text at all"}]}
    monkeypatch.setattr(ask_app, "_stub_answer", lambda user: bad)
    assert ask(server, QUESTION)["status"] == "blocked"
    assert rows() == []


def test_refusal_is_prepared_too(server, monkeypatch):
    monkeypatch.setattr(ask_app, "_stub_answer", lambda user: {"refused": True, "reason": "x"})
    assert "prepared" not in ask(server, QUESTION)
    again = ask(server, QUESTION)
    assert again["status"] == "refused" and again["prepared"] and again["reason"] == ask_app.NOT_COVERED_REPLY


def test_changed_official_text_is_not_served_from_cache(server):
    ask(server, QUESTION)
    conn = db.connect()
    old = conn.execute("SELECT text FROM field WHERE measure_id = 'prop-a' AND name = 'fiscal_effect'").fetchone()[0]
    try:
        with conn:
            conn.execute("UPDATE field SET text = ? WHERE measure_id = 'prop-a' AND name = 'fiscal_effect'",
                         (old + " Corrected.",))
        assert "prepared" not in ask(server, QUESTION)
    finally:
        with conn:
            conn.execute("UPDATE field SET text = ? WHERE measure_id = 'prop-a' AND name = 'fiscal_effect'", (old,))
    assert "prepared" in ask(server, QUESTION)  # the entry for the original text is still there


@pytest.mark.parametrize("setting", ["ANSWER_MODEL", "REVIEW_MODEL"])
def test_changed_model_is_not_served_from_cache(server, monkeypatch, setting):
    ask(server, QUESTION)
    monkeypatch.setattr(config, setting, "another/model")
    assert "prepared" not in ask(server, QUESTION)


def test_changed_bias_version_is_not_served_from_cache(server, monkeypatch):
    ask(server, QUESTION)
    monkeypatch.setattr(engine, "BIAS_VERSION", "test-next")
    assert "prepared" not in ask(server, QUESTION)


def test_entry_failing_the_recheck_falls_through_to_a_live_answer(server):
    ask(server, QUESTION)
    with cache._connect() as conn:
        result = json.loads(conn.execute("SELECT result FROM answer").fetchone()[0])
        result["points"][0]["quote"] = "a quote that is nowhere in the official text"
        conn.execute("UPDATE answer SET result = ?", (json.dumps(result),))
    live = ask(server, QUESTION)
    assert live["status"] == "answered" and "prepared" not in live
    assert ask(server, QUESTION)["prepared"]  # the live answer replaced the bad entry


def _load_warm_script():
    spec = importlib.util.spec_from_file_location("warm_ask_cache", config.ROOT / "scripts" / "warm_ask_cache.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_warm_script_fills_the_cache_and_skips_cached_questions(server, monkeypatch, caplog):
    warm = _load_warm_script().warm
    ballot, bias = ServiceClient("ballot"), ServiceClient("bias")
    assert warm(ballot, bias, pause=0) == 0
    assert len(rows()) == 2 * len(SUGGESTED_QUESTIONS)

    calls = []
    real = ai.chat_json
    monkeypatch.setattr(ai, "chat_json", lambda *a, **k: calls.append(a[0]) or real(*a, **k))
    with caplog.at_level(logging.INFO, logger="thinkballot.warm"):
        assert warm(ballot, bias, pause=0) == 0
    assert calls == []
    assert caplog.text.count("status=cached") == 2 * len(SUGGESTED_QUESTIONS)
