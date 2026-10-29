"""Answers to the suggested questions, prepared in advance, in their own small SQLite file.

The site promises that questions are never stored or logged. That holds: only the fixed
SUGGESTED_QUESTIONS (matched by exact text) are ever written here. A question a voter types is never
stored, not even as a hash.

Spanish and Chinese versions of those answers sit in a second table, keyed by the English entry's key,
the language and both translation models, with a hash of the English points they were made from.
"""

import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone

from ... import config
from ...suggested import SUGGESTED_QUESTIONS

log = logging.getLogger("thinkballot.ask")


def _sha256(text):
    return hashlib.sha256(text.encode()).hexdigest()


def make_key(measure_id, question, sent_text):
    """Key for one prepared answer, or None for a typed question (never cached).

    `sent_text` is everything sent to the answer model except the question, so a change to the official
    text, or to either model, means the old entry is simply not found. The Bias Buster version is stored
    with the entry and compared when it is used. Answers from the offline stub get keys of their own, so
    they can never be served as real ones (translations hang off these keys too).
    """
    if question not in SUGGESTED_QUESTIONS:
        return None
    parts = [measure_id, question, _sha256(sent_text), config.ANSWER_MODEL, config.REVIEW_MODEL]
    return _sha256("\n".join(parts + (["stub"] if config.AI_PROVIDER == "stub" else [])))


def _connect():
    config.ASK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.ASK_CACHE_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS answer (key TEXT PRIMARY KEY, measure_id TEXT NOT NULL, "
                 "bias_version TEXT NOT NULL, result TEXT NOT NULL, prepared REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS translation (key TEXT NOT NULL, lang TEXT NOT NULL, "
                 "translate_model TEXT NOT NULL, check_model TEXT NOT NULL, rules TEXT NOT NULL, "
                 "measure_id TEXT NOT NULL, english_hash TEXT NOT NULL, points TEXT NOT NULL, prepared REAL NOT NULL, "
                 "PRIMARY KEY (key, lang, translate_model, check_model, rules))")
    return conn


def get(key):
    """(result, bias_version, prepared date as YYYY-MM-DD) or None. A broken cache is just a miss."""
    try:
        with _connect() as conn:
            row = conn.execute("SELECT result, bias_version, prepared FROM answer WHERE key = ?",
                               (key,)).fetchone()
    except sqlite3.Error as exc:
        log.warning("ask cache read failed: %s", type(exc).__name__)
        return None
    if not row:
        return None
    day = datetime.fromtimestamp(row[2], timezone.utc).date().isoformat()
    return json.loads(row[0]), row[1], day


def put(key, measure_id, bias_version, result):
    try:
        with _connect() as conn:
            conn.execute("INSERT OR REPLACE INTO answer (key, measure_id, bias_version, result, prepared) "
                         "VALUES (?, ?, ?, ?, ?)", (key, measure_id, bias_version, json.dumps(result), time.time()))
    except sqlite3.Error as exc:
        log.warning("ask cache write failed: %s", type(exc).__name__)


def points_hash(points):
    """Hash of the English points (claim and quote) a translation was made from."""
    return _sha256(json.dumps([[p["claim"], p["quote"]] for p in points], ensure_ascii=False))


def get_translation(key, lang, rules):
    """(translated points, hash of the English points they came from) for the current translation
    models and rules (translate.RULES: its prompts and checks), or None. A broken cache is just a miss."""
    try:
        with _connect() as conn:
            row = conn.execute("SELECT points, english_hash FROM translation WHERE key = ? AND lang = ? "
                               "AND translate_model = ? AND check_model = ? AND rules = ?",
                               (key, lang, config.TRANSLATE_MODEL, config.TRANSLATE_CHECK_MODEL, rules)).fetchone()
    except sqlite3.Error as exc:
        log.warning("ask cache read failed: %s", type(exc).__name__)
        return None
    return (json.loads(row[0]), row[1]) if row else None


def put_translation(key, measure_id, lang, rules, english_hash, points):
    """Store a translation that passed both checks (the caller's job), with the models and rules that made it."""
    try:
        with _connect() as conn:
            conn.execute("INSERT OR REPLACE INTO translation (key, lang, translate_model, check_model, rules, "
                         "measure_id, english_hash, points, prepared) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (key, lang, config.TRANSLATE_MODEL, config.TRANSLATE_CHECK_MODEL, rules, measure_id,
                          english_hash, json.dumps(points, ensure_ascii=False), time.time()))
    except sqlite3.Error as exc:
        log.warning("ask cache write failed: %s", type(exc).__name__)
