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
    documents TEXT NOT NULL DEFAULT '[]',  -- JSON [{label, url}]: official PDFs, linked not parsed
    notes TEXT NOT NULL DEFAULT '[]',      -- JSON list of plain notes about the source (e.g. "from a resolution")
    position INTEGER NOT NULL      -- ballot order
);
CREATE TABLE IF NOT EXISTS field (
    measure_id TEXT NOT NULL REFERENCES measure(id),
    name TEXT NOT NULL,
    text TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_label TEXT NOT NULL,
    note TEXT,                     -- e.g. "Text read from a scanned official PDF"
    PRIMARY KEY (measure_id, name)
);
-- Official translations (the Secretary of State's Spanish and Chinese guides): the same fields, word for
-- word from the translated guide, plus the translated title and links to its PDFs. A field with no
-- official translation is simply absent and the page shows the English text with a note.
CREATE TABLE IF NOT EXISTS translation (
    measure_id TEXT NOT NULL REFERENCES measure(id),
    lang TEXT NOT NULL,            -- "es", "zh"
    name TEXT NOT NULL,            -- "title" or a field name
    text TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_label TEXT NOT NULL,
    PRIMARY KEY (measure_id, lang, name)
);
CREATE TABLE IF NOT EXISTS translation_doc (
    measure_id TEXT NOT NULL REFERENCES measure(id),
    lang TEXT NOT NULL,
    kind TEXT NOT NULL,            -- "analysis", "arguments": the translated guide's PDF for that section
    url TEXT NOT NULL,
    PRIMARY KEY (measure_id, lang, kind)
);
"""

LANGS = ("es", "zh")


def connect(path=None):
    """Read-write connection, used only by the seed script."""
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, column, decl in (("measure", "notes", "TEXT NOT NULL DEFAULT '[]'"), ("field", "note", "TEXT")):
        if column not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")  # databases made before the column
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
        conn.execute("DELETE FROM translation")
        conn.execute("DELETE FROM translation_doc")
        conn.execute("DELETE FROM field")
        conn.execute("DELETE FROM measure")
        conn.execute("DELETE FROM election")
        conn.execute("INSERT INTO election (id, name, date) VALUES (?, ?, ?)",
                     (election["id"], election["name"], election["date"]))
        for pos, m in enumerate(measures):
            jur = m.get("jurisdiction") or {"level": "state"}
            conn.execute(
                "INSERT INTO measure (id, election_id, number, title, title_source_url, topics, arguments_url, "
                "level, county, district, documents, notes, position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (m["id"], election["id"], m["number"], m["title"]["text"], m["title"]["source_url"],
                 json.dumps(m.get("topics", [])), m.get("arguments_url"), jur.get("level", "state"),
                 jur.get("county"), jur.get("name") if jur.get("level") == "local" else None,
                 json.dumps(m.get("documents", [])), json.dumps(m.get("notes", [])), pos))
            for name in FIELDS:
                f = m["fields"].get(name)
                if f:  # unsourced fields are simply absent
                    conn.execute(
                        "INSERT INTO field (measure_id, name, text, source_url, source_label, note) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (m["id"], name, f["text"], f["source_url"], f["source_label"], f.get("source_note")))
            for lang, tr in m.get("translations", {}).items():
                for name, f in [("title", tr["title"])] + [(n, tr["fields"][n]) for n in FIELDS if n in tr["fields"]]:
                    conn.execute(
                        "INSERT INTO translation (measure_id, lang, name, text, source_url, source_label) "
                        "VALUES (?, ?, ?, ?, ?, ?)", (m["id"], lang, name, f["text"], f["source_url"], f["source_label"]))
                for kind, url in tr.get("documents", {}).items():
                    conn.execute("INSERT INTO translation_doc (measure_id, lang, kind, url) VALUES (?, ?, ?, ?)",
                                 (m["id"], lang, kind, url))


def election(conn):
    row = conn.execute("SELECT * FROM election LIMIT 1").fetchone()
    return dict(row) if row else None


def _translations(conn, lang, measure_id=None):
    """{measure_id: {name: field}} of the official translation into lang (empty for English)."""
    if lang not in LANGS:
        return {}
    sql, args = "SELECT * FROM translation WHERE lang = ?", [lang]
    if measure_id:
        sql, args = sql + " AND measure_id = ?", args + [measure_id]
    out = {}
    for r in conn.execute(sql, args):
        out.setdefault(r["measure_id"], {})[r["name"]] = {
            "text": r["text"], "source_url": r["source_url"], "source_label": r["source_label"], "lang": lang}
    return out


def list_measures(conn, lang=None):
    tr = _translations(conn, lang)
    rows = conn.execute(
        "SELECT m.id, m.number, m.title, m.topics, m.level, m.county, m.district, "
        "COALESCE(f.text, q.text) AS summary, t.text AS measure_type FROM measure m "
        "LEFT JOIN field q ON q.measure_id = m.id AND q.name = 'ballot_question' "
        "LEFT JOIN field f ON f.measure_id = m.id AND f.name = 'summary' "
        "LEFT JOIN field t ON t.measure_id = m.id AND t.name = 'measure_type' ORDER BY m.position").fetchall()
    out = []
    for r in rows:
        m = dict(r, topics=json.loads(r["topics"]))
        t = tr.get(m["id"], {})
        m["translated"] = sorted(n for n in ("title", "summary", "measure_type") if n in t)
        for name in m["translated"]:  # official translation where there is one; English otherwise
            m[name] = t[name]["text"]
        out.append(m)
    return out


def get_measure(conn, measure_id, lang=None):
    """A measure with its official fields. With lang ("es", "zh"), each field that has an official
    translation is replaced by it (marked "lang"); the others stay English. "translation" lists the
    translated field names and the translated guide's PDFs."""
    row = conn.execute("SELECT * FROM measure WHERE id = ?", (measure_id,)).fetchone()
    if not row:
        return None
    fields = {
        r["name"]: {"text": r["text"], "source_url": r["source_url"], "source_label": r["source_label"],
                    "note": r["note"]}
        for r in conn.execute("SELECT * FROM field WHERE measure_id = ?", (measure_id,))
    }
    tr = _translations(conn, lang, measure_id).get(measure_id, {})
    title, title_url = row["title"], row["title_source_url"]
    if "title" in tr:
        title, title_url = tr["title"]["text"], tr["title"]["source_url"]
    for name, f in tr.items():
        if name in fields:
            fields[name] = f
    docs = {r["kind"]: r["url"] for r in conn.execute(
        "SELECT kind, url FROM translation_doc WHERE measure_id = ? AND lang = ?", (measure_id, lang))} if tr else {}
    return {
        "translation": {"lang": lang, "fields": sorted(tr), "documents": docs} if lang in LANGS else None,
        "id": row["id"],
        "number": row["number"],
        "title": title,
        "title_source_url": title_url,
        "topics": json.loads(row["topics"]),
        "arguments_url": row["arguments_url"],
        "level": row["level"], "county": row["county"], "district": row["district"],
        "documents": json.loads(row["documents"]),
        "notes": json.loads(row["notes"]),
        "fields": fields,
        "missing": [name for name in FIELDS if name not in fields],
    }
