"""SQLite storage for measures. Every text field is stored with the official page it came from."""

import sqlite3

from ... import config

# The fields a measure card can show, in display order. YES always comes before NO.
FIELDS = ["summary", "yes_means", "no_means", "fiscal_effect", "argument_for", "argument_against"]

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
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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
            conn.execute(
                "INSERT INTO measure (id, election_id, number, title, title_source_url, position) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (m["id"], election["id"], m["number"], m["title"]["text"], m["title"]["source_url"], pos))
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
        "SELECT m.id, m.number, m.title, f.text AS summary FROM measure m "
        "LEFT JOIN field f ON f.measure_id = m.id AND f.name = 'summary' ORDER BY m.position").fetchall()
    return [dict(r) for r in rows]


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
        "fields": fields,
        "missing": [name for name in FIELDS if name not in fields],
    }
