"""SQLite storage for measures. Every text field is stored with the official page it came from."""

import json
import sqlite3

from ... import config

# The fields a measure card can show, in display order. YES always comes before NO.
FIELDS = ["measure_type", "summary", "yes_means", "no_means", "fiscal_effect", "argument_for", "argument_against",
          "supporters", "opponents", "analysis", "district", "ballot_question"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS election (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS measure (
    id TEXT PRIMARY KEY,           -- e.g. "prop-1", used in share links
    election_id TEXT NOT NULL REFERENCES election(id),
    number TEXT NOT NULL,          -- as printed on the ballot
    title TEXT NOT NULL,
    title_source_url TEXT NOT NULL,
    topics TEXT NOT NULL,
    arguments_url TEXT,            -- the guide's page with the full arguments and rebuttals
    level TEXT NOT NULL DEFAULT 'state',   -- 'state' or 'local'
    county TEXT,                   -- local measures: county whose registrar publishes it
    district TEXT,                 -- local measures: city / school / special district
    documents TEXT NOT NULL DEFAULT '[]',  -- JSON [{label, url}]: official PDFs, linked not parsed          -- JSON list of ThinkBallot topic labels (checked by Bias Buster)
    position INTEGER NOT NULL      -- ballot order
);
CREATE TABLE IF NOT EXISTS field (
    measure_id TEXT NOT NULL REFERENCES measure(id),
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_label TEXT NOT NULL,
    PRIMARY KEY (measure_id, name)
);
"""


def connect(path=None):
    """Read-write connection, used only by the seed script."""
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def connect_readonly(path=None):
    """The ballot service only reads; the release tree is read-only on the server."""
    path = path or config.DB_PATH
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def replace_all(conn, election, measures):
    """Replace the whole dataset in one transaction (used by the seed script)."""
    with conn:
        conn.execute("DELETE FROM field")
        conn.execute("DELETE FROM measure")
        conn.execute("DELETE FROM election")
        conn.execute("INSERT INTO election (id, name, date) VALUES (?, ?, ?)",
                     (election["id"], election["name"], election["date"]))
        for pos, m in enumerate(measures):
            jur = m.get("jurisdiction") or {"level": "state"}
            conn.execute(
                "INSERT INTO measure (id, election_id, number, title, title_source_url, topics, arguments_url, "
                "level, county, district, documents, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (m["id"], election["id"], m["number"], m["title"]["text"], m["title"]["source_url"],
                 json.dumps(m.get("topics", [])), m.get("arguments_url"), jur.get("level", "state"),
                 jur.get("county"), jur.get("name") if jur.get("level") == "local" else None,
                 json.dumps(m.get("documents", [])), pos))
            for name in FIELDS:
                f = m["fields"].get(name)
                if f:  # unsourced fields are simply absent
                    conn.execute(
                        "INSERT INTO field (measure_id, name, text, source_url, source_label) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (m["id"], name, f["text"], f["source_url"], f["source_label"]))


def election(conn):
    row = conn.execute("SELECT * FROM election LIMIT 1").fetchone()
    return dict(row) if row else None


def list_measures(conn):
    rows = conn.execute(
        "SELECT m.id, m.number, m.title, m.topics, m.level, m.county, m.district, "
        "COALESCE(f.text, q.text) AS summary, t.text AS measure_type FROM measure m "
        "LEFT JOIN field q ON q.measure_id = m.id AND q.name = 'ballot_question' "
        "LEFT JOIN field f ON f.measure_id = m.id AND f.name = 'summary' "
        "LEFT JOIN field t ON t.measure_id = m.id AND t.name = 'measure_type' ORDER BY m.position").fetchall()
    return [dict(r, topics=json.loads(r["topics"])) for r in rows]


def get_measure(conn, measure_id):
    row = conn.execute("SELECT * FROM measure WHERE id = ?", (measure_id,)).fetchone()
    if not row:
        return None
    fields = {
        r["name"]: {"text": r["text"], "source_url": r["source_url"], "source_label": r["source_label"]}
        for r in conn.execute("SELECT * FROM field WHERE measure_id = ?", (measure_id,))
    }
    return {
        "id": row["id"],
        "number": row["number"],
        "title": row["title"],
        "title_source_url": row["title_source_url"],
        "topics": json.loads(row["topics"]),
        "arguments_url": row["arguments_url"],
        "level": row["level"], "county": row["county"], "district": row["district"],
        "documents": json.loads(row["documents"]),
        "fields": fields,
        "missing": [name for name in FIELDS if name not in fields],
    }
