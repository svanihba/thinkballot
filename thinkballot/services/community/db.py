"""The community service's own SQLite database: accounts, comments, flags, facts and ratings.

Kept apart from the official ballot data on purpose: nothing here can change an official card.
"""

import sqlite3

from ... import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS user (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,     -- sign-in name; never shown publicly
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,  -- public display name
    pw_hash TEXT NOT NULL,
    is_mod INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS comment (
    id INTEGER PRIMARY KEY,
    measure_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES user(id),
    text TEXT NOT NULL,
    hidden INTEGER NOT NULL DEFAULT 0,      -- 1 = hidden by flags or a moderator
    reviewed INTEGER NOT NULL DEFAULT 0,    -- 1 = a moderator restored it; flags no longer hide it
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS flag (
    comment_id INTEGER NOT NULL REFERENCES comment(id),
    user_id INTEGER NOT NULL REFERENCES user(id),
    PRIMARY KEY (comment_id, user_id)
);
CREATE TABLE IF NOT EXISTS fact (
    id INTEGER PRIMARY KEY,
    measure_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES user(id),
    text TEXT NOT NULL,
    citation_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending -> bridged -> vetted, or rejected
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS rating (
    fact_id INTEGER NOT NULL REFERENCES fact(id),
    user_id INTEGER NOT NULL REFERENCES user(id),
    helpful INTEGER NOT NULL,               -- 1 helpful, 0 not helpful
    leaning TEXT NOT NULL,                  -- the rater's own leaning on this measure: yes, no, undecided
    PRIMARY KEY (fact_id, user_id)
);
"""


def connect(path=None):
    path = path or config.COMMUNITY_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
