"""Problem reports sent from "Report an error", kept in a small private SQLite file for 60 days.

Nothing here is shown on the site; the owner reads the file on the server.
"""

import os
import sqlite3
import threading
import unicodedata
from datetime import datetime, timedelta, timezone

from ... import config

KINDS = ("error", "security", "other")
KEEP_DAYS = 60
MESSAGE_MIN, MESSAGE_MAX, CONTACT_MAX, PAGE_MAX = 10, 2000, 200, 300
PER_NETWORK_HOUR, SITEWIDE_HOUR = 5, 200
SECURITY_SITEWIDE_HOUR = 50  # its own cap, so a flood of other reports can't block security reports

_lock = threading.Lock()


def _connect():
    path = config.PROBLEM_REPORTS_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT, 0o600))  # private before the first row is written
    conn = sqlite3.connect(path, timeout=5)
    conn.execute("CREATE TABLE IF NOT EXISTS report (id INTEGER PRIMARY KEY, created TEXT NOT NULL, "
                 "kind TEXT NOT NULL, page TEXT NOT NULL, message TEXT NOT NULL, contact TEXT NOT NULL, "
                 "lang TEXT NOT NULL)")
    return conn


def clean(text):
    """Line breaks as one character (as the browser counts them) and no control characters but newline and tab,
    so nothing typed can drive the terminal of whoever reads the file."""
    text = (text or "").replace("\r\n", "\n")
    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) != "Cc").strip()


def _cutoff():
    return (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")


def save(kind, page, message, contact, lang, now=None):
    now = now or datetime.now(timezone.utc)
    with _lock, _connect() as conn:
        conn.execute("INSERT INTO report (created, kind, page, message, contact, lang) VALUES (?, ?, ?, ?, ?, ?)",
                     (now.isoformat(timespec="seconds"), kind, page, message, contact, lang))
        conn.execute("DELETE FROM report WHERE created < ?", (_cutoff(),))


def purge():
    """Delete reports past 60 days even when no new report comes in to trigger it."""
    if not config.PROBLEM_REPORTS_DB_PATH.exists():
        return
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM report WHERE created < ?", (_cutoff(),))
