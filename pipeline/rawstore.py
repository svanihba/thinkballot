"""The raw store: the ONLY thing the crawler and the extraction system share.

The crawler (and supervised browser captures) write here; extraction only reads. Layout under
data/raw/:

    objects/<sha256[:2]>/<sha256>   page bytes exactly as received, stored once per distinct content
    crawl.sqlite3                   runs and fetches (crawl metadata)
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIR = ROOT / "data" / "raw"

SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL,
    kind TEXT NOT NULL,              -- 'crawl' (unattended crawler) or 'capture' (supervised browser session)
    agent TEXT NOT NULL,             -- user agent, or who captured it
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT,                     -- ok / partial / blocked / failed
    notes TEXT
);
CREATE TABLE IF NOT EXISTS fetch (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES run(id),
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    final_url TEXT,
    parent_url TEXT,                 -- page the link was found on (NULL for seeds)
    depth INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL,
    http_status INTEGER,
    content_type TEXT,
    etag TEXT,
    last_modified TEXT,
    sha256 TEXT,                     -- NULL when nothing was stored (error, blocked, not modified)
    size INTEGER,
    unchanged INTEGER NOT NULL DEFAULT 0,  -- 1 = 304 Not Modified, or same bytes as the previous fetch
    blocked INTEGER NOT NULL DEFAULT 0,    -- 1 = the site refused automated access (robots.txt or 403 challenge)
    error TEXT
);
CREATE INDEX IF NOT EXISTS fetch_source_url ON fetch (source_id, url, fetched_at);
"""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RawStore:
    def __init__(self, directory=None):
        self.dir = Path(directory or DEFAULT_DIR)
        (self.dir / "objects").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "crawl.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---------- writing (crawler side) ----------
    def put(self, data):
        sha = hashlib.sha256(data).hexdigest()
        path = self.object_path(sha)
        if not path.exists():
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
        return sha

    def start_run(self, source_id, kind, agent, notes=None):
        with self.db:
            cur = self.db.execute("INSERT INTO run (source_id, kind, agent, started_at, notes) VALUES (?, ?, ?, ?, ?)",
                                  (source_id, kind, agent, now(), notes))
        return cur.lastrowid

    def finish_run(self, run_id, status):
        with self.db:
            self.db.execute("UPDATE run SET finished_at = ?, status = ? WHERE id = ?", (now(), status, run_id))

    def record(self, run_id, source_id, url, **f):
        cols = ["run_id", "source_id", "url", "fetched_at"] + list(f)
        vals = [run_id, source_id, url, now()] + list(f.values())
        with self.db:
            self.db.execute(f"INSERT INTO fetch ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)

    def last_good(self, source_id, url):
        """The most recent fetch of this URL that stored content (for ETag / unchanged checks)."""
        return self.db.execute(
            "SELECT * FROM fetch WHERE source_id = ? AND url = ? AND sha256 IS NOT NULL "
            "ORDER BY fetched_at DESC, id DESC LIMIT 1", (source_id, url)).fetchone()

    def stored_content_type(self, source_id, url, sha):
        """The content type recorded with these bytes (a 304 Not Modified response carries none)."""
        row = self.db.execute(
            "SELECT content_type FROM fetch WHERE source_id = ? AND url = ? AND sha256 = ? AND content_type IS NOT NULL "
            "ORDER BY fetched_at DESC, id DESC LIMIT 1", (source_id, url, sha)).fetchone()
        return row["content_type"] if row else None

    # ---------- reading (extraction side) ----------
    def object_path(self, sha):
        return self.dir / "objects" / sha[:2] / sha

    def read(self, sha):
        return self.object_path(sha).read_bytes()

    def latest_pages(self, source_id):
        """{url: fetch row} — the newest stored content per URL for a source, with its provenance."""
        rows = self.db.execute(
            "SELECT f.*, r.kind AS run_kind, r.agent AS run_agent FROM fetch f JOIN run r ON r.id = f.run_id "
            "WHERE f.source_id = ? AND f.sha256 IS NOT NULL ORDER BY f.fetched_at, f.id", (source_id,)).fetchall()
        latest = {}
        for row in rows:
            latest[row["url"]] = row
        return latest

    def summary(self):
        return [dict(r) for r in self.db.execute(
            "SELECT source_id, COUNT(*) AS fetches, SUM(sha256 IS NOT NULL) AS stored, SUM(blocked) AS blocked, "
            "MAX(fetched_at) AS last FROM fetch GROUP BY source_id")]


def load_sources(path=None):
    """pipeline/sources.json plus one file per source in pipeline/sources.d/ (so sources can be added
    without editing a shared file)."""
    data = json.loads(Path(path or ROOT / "pipeline" / "sources.json").read_text())
    sources = list(data["sources"])
    if path is None:
        sources += [json.loads(f.read_text()) for f in sorted((ROOT / "pipeline" / "sources.d").glob("*.json"))]
    return {s["id"]: s for s in sources}
