"""Answers to the suggested questions, prepared in advance, in their own small SQLite file.

The site promises that questions are never stored or logged. That holds: only the fixed
SUGGESTED_QUESTIONS (matched by exact text) are ever written here. A question a voter types is never
stored, not even as a hash.
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
    with the entry and compared when it is used.
    """
    if question not in SUGGESTED_QUESTIONS:
        return None
    return _sha256("\n".join([measure_id, question, _sha256(sent_text), config.ANSWER_MODEL,
                              config.REVIEW_MODEL]))


def _connect():
    config.ASK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.ASK_CACHE_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS answer (key TEXT PRIMARY KEY, measure_id TEXT NOT NULL, "
                 "bias_version TEXT NOT NULL, result TEXT NOT NULL, prepared REAL NOT NULL)")
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
