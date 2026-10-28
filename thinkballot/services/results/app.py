"""results service: official statewide proposition results from the California Secretary of State.

No timers or background threads: a request for results fetches the official feed only when the last
attempt is more than five minutes old (one worker claims the attempt in SQLite, everyone else serves
the stored copy at once). The last good copy is kept in its own SQLite database in the writable state
directory, and is served with its own time when a later fetch fails or the feed changes format.
Results are fetched only from the polls closing on election day until feed.RESULTS_WINDOW_DAYS later.
"""

import datetime as dt
import json
import logging
import sqlite3
import time
from pathlib import Path

import requests
from flask import jsonify

from ... import config
from ...servicekit import ServiceClient, ServiceError, make_service
from . import feed

log = logging.getLogger("thinkballot.results")

USER_AGENT = "ThinkBallotBot/0.1 (+https://demo.thinkballot.com/about; nonpartisan voter guide)"
CONNECT_TIMEOUT, READ_TIMEOUT = 3.05, 8
ATTEMPTS, BACKOFF_SECONDS, DEADLINE_SECONDS = 3, 1.0, 20


class FetchError(Exception):
    pass


def http_fetch(url=feed.SOURCE_URL, sleep=time.sleep):
    """GET the official feed: per-request timeouts, retries with backoff, one log line per request."""
    started = time.monotonic()
    for attempt in range(1, ATTEMPTS + 1):
        t0 = time.monotonic()
        try:
            resp = requests.get(url, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), stream=True,
                                headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            body = resp.raw.read(feed.MAX_BYTES + 1, decode_content=True)
            resp.close()
            log.info("results fetch %s attempt %d -> %s, %d bytes in %.0f ms", url, attempt, resp.status_code,
                     len(body), (time.monotonic() - t0) * 1000)
            if resp.status_code == 200:
                if not resp.headers.get("content-type", "").startswith("application/json"):
                    raise FetchError(f"content-type {resp.headers.get('content-type')!r}")
                return body
            if resp.status_code < 500 and resp.status_code != 429:
                raise FetchError(f"HTTP {resp.status_code}")  # retrying won't help
            error = f"HTTP {resp.status_code}"
        except requests.RequestException as exc:
            error = type(exc).__name__
            log.warning("results fetch %s attempt %d failed: %s in %.0f ms", url, attempt, error,
                        (time.monotonic() - t0) * 1000)
        delay = BACKOFF_SECONDS * 2 ** (attempt - 1)
        if attempt == ATTEMPTS or time.monotonic() - started + delay > DEADLINE_SECONDS:
            break
        sleep(delay)
    raise FetchError(error)


def fixture_fetch(path):
    """Preview only (TB_RESULTS_FIXTURE): read a recorded feed from disk instead of the network."""
    def fetch():
        log.info("results fetch fixture %s", path)
        return Path(path).read_bytes()
    return fetch


def ballot_catalog():
    """(election date, {number: official title}) for the statewide propositions, from the ballot service."""
    ballot = ServiceClient("ballot")
    election = ballot.get("/election")
    listing = ballot.get("/measures", level="state")
    if not election or not listing:
        raise ServiceError("ballot", "no election loaded")
    return election["date"], {m["number"]: m["title"] for m in listing["measures"]}


# ---------- storage: the last good copy, and when the last attempt was made ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
  id INTEGER PRIMARY KEY CHECK (id = 1),   -- only the last good copy
  election_date TEXT NOT NULL,
  fetched_at TEXT NOT NULL,                -- when ThinkBallot fetched it (UTC)
  results TEXT NOT NULL,                   -- parsed, validated results (JSON)
  raw TEXT NOT NULL                        -- the response exactly as received
);
CREATE TABLE IF NOT EXISTS attempt (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  at REAL NOT NULL,                        -- unix time of the last fetch attempt
  error TEXT
);
"""


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.executescript(SCHEMA)
    return conn


def claim_attempt(conn, now_ts, max_age):
    """True for exactly one caller per max_age seconds, across threads and worker processes."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute("SELECT at FROM attempt WHERE id = 1").fetchone()
        if row and now_ts - row[0] < max_age:
            conn.execute("ROLLBACK")
            return False
        conn.execute("INSERT INTO attempt (id, at, error) VALUES (1, ?, NULL) "
                     "ON CONFLICT(id) DO UPDATE SET at = excluded.at, error = NULL", (now_ts,))
        conn.execute("COMMIT")
        return True
    except Exception:
        conn.execute("ROLLBACK")
        raise


def refresh_if_stale(conn, fetch, election_date, titles, now, max_age=None, preview=False):
    """Fetch and store the feed if the last attempt is older than max_age. Never raises for feed problems.

    titles: {number: official title} of this election's statewide propositions.
    """
    max_age = config.RESULTS_MAX_AGE_SECONDS if max_age is None else max_age
    if not preview and not feed.in_window(now, election_date):
        return  # before the polls close (or long after): nothing to fetch
    if not claim_attempt(conn, now.timestamp(), max_age):
        return
    try:
        body = fetch()
        parsed = feed.parse(body, election_date, titles)
    except (FetchError, feed.FeedError, OSError) as exc:
        log.warning("results: keeping the last good copy: %s: %s", type(exc).__name__, exc)
        conn.execute("UPDATE attempt SET error = ? WHERE id = 1", (f"{type(exc).__name__}: {exc}"[:300],))
        return
    raw = body.decode("utf-8") if isinstance(body, bytes) else body
    fetched_at = now.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    conn.execute("INSERT INTO snapshot (id, election_date, fetched_at, results, raw) VALUES (1, ?, ?, ?, ?) "
                 "ON CONFLICT(id) DO UPDATE SET election_date = excluded.election_date, "
                 "fetched_at = excluded.fetched_at, results = excluded.results, raw = excluded.raw",
                 (election_date, fetched_at, json.dumps(parsed), raw))
    log.info("results: stored %d measures, as of %s", len(parsed["measures"]), parsed["as_of"])


def time_text(when):
    """"November 3, 2026, 9:45 p.m. PT" (the Secretary of State's own style)."""
    p = when.astimezone(feed.PACIFIC)
    hour = p.hour % 12 or 12
    return f"{p:%B} {p.day}, {p.year}, {hour}:{p:%M} {'a.m.' if p.hour < 12 else 'p.m.'} PT"


def current(conn, election_date, preview=False):
    """What voters see: the last good copy for this election, or {"available": False}."""
    row = conn.execute("SELECT election_date, fetched_at, results FROM snapshot WHERE id = 1").fetchone()
    if not row or row[0] != election_date:
        return {"available": False}
    parsed = json.loads(row[2])
    as_of = dt.datetime.fromisoformat(parsed["as_of"])
    measures = {}
    for number, r in parsed["measures"].items():
        measures[number] = dict(r, yes_bar=float(r["yes_percent"]), no_bar=float(r["no_percent"]))
    return {"available": True, "election_date": election_date,
            "status": "certified" if config.RESULTS_CERTIFIED else "unofficial",
            "as_of": parsed["as_of"], "as_of_text": time_text(as_of), "fetched_at": row[1],
            "reporting": parsed["reporting"], "measures": measures, "preview": preview,
            "source_name": feed.SOURCE_NAME, "source_url": feed.SOURCE_URL, "source_page": feed.SOURCE_PAGE}


def create_app(db_path=None, fetch=None, catalog=None, clock=None):
    app = make_service("results")
    preview = bool(config.RESULTS_FIXTURE) and fetch is None
    fetch = fetch or (fixture_fetch(config.RESULTS_FIXTURE) if preview else http_fetch)
    catalog = catalog or ballot_catalog
    clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
    path = Path(db_path or config.RESULTS_DB_PATH)
    if preview:  # test data never lands in the real results database
        path = path.with_name("results-preview.sqlite3")
        log.warning("results: PREVIEW MODE, serving test data from %s", config.RESULTS_FIXTURE)

    @app.get("/results")
    def results():
        try:
            election_date, titles = catalog()
        except ServiceError as exc:
            log.warning("results: ballot data unavailable: %s", exc)
            return jsonify(available=False)
        conn = connect(path)
        try:
            refresh_if_stale(conn, fetch, election_date, titles, clock(), preview=preview)
            return jsonify(current(conn, election_date, preview=preview))
        finally:
            conn.close()

    return app
