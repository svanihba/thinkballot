"""Rate limits shared by every worker process, kept in a small SQLite file.

Keys are hashed (no IP addresses are stored), IPv6 clients are grouped by their /64, and rows older
than a day are pruned. Used for AI questions (per client and site-wide) and community actions.
"""

import hashlib
import ipaddress
import sqlite3
import threading
import time

from . import config

_lock = threading.Lock()


def client_key(ip):
    """IPv4 address as is; IPv6 by its /64, since one user can rotate through a whole /64."""
    try:
        addr = ipaddress.ip_address(ip or "")
    except ValueError:
        return "unknown"
    if addr.version == 6:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def _connect():
    config.RATE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.RATE_DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS hit (bucket TEXT NOT NULL, ts REAL NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS hit_bucket_ts ON hit (bucket, ts)")
    return conn


def allow(action, key, limits):
    """Record one hit and say whether it is within every limit.

    limits: [(max_hits, window_seconds), ...]; key None means a site-wide limit for the action.
    """
    bucket = action + ":" + (hashlib.sha256(key.encode()).hexdigest()[:24] if key else "*")
    now = time.time()
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM hit WHERE ts < ?", (now - 86400,))
        for max_hits, window in limits:
            n = conn.execute("SELECT COUNT(*) FROM hit WHERE bucket = ? AND ts > ?",
                             (bucket, now - window)).fetchone()[0]
            if n >= max_hits:
                return False
        conn.execute("INSERT INTO hit (bucket, ts) VALUES (?, ?)", (bucket, now))
    return True
