"""search service: full-text search and topic filters over the measures.

It reads measures only through the ballot service's API, so the search method can get smarter later
(for example SQLite FTS or embeddings) without the web pages changing.
"""

import re

from flask import abort, jsonify, request

from ...servicekit import ServiceClient, ServiceError, make_service


def _words(text):
    return re.findall(r"[a-z0-9$%.]+", (text or "").lower())


def score(measure, terms):
    """How well a measure matches: title hits count most, then topics, then any official text."""
    title = " ".join(_words(f"prop {measure['number']} {measure['title']}"))
    topics = " ".join(measure["topics"])
    body = " ".join(_words(" ".join(f["text"] for f in measure["fields"].values())))
    total = 0
    for t in terms:
        hits = (3 * (t in title)) + (2 * (t in topics)) + body.count(t)
        if not hits:
            return 0  # every term must appear somewhere
        total += hits
    return total


def snippet(measure, terms, width=160):
    """A short piece of official text around the first matching term."""
    for name in ("summary", "yes_means", "no_means", "fiscal_effect", "argument_for", "argument_against"):
        f = measure["fields"].get(name)
        if not f:
            continue
        low = f["text"].lower()
        for t in terms:
            i = low.find(t)
            if i >= 0:
                start = max(0, i - width // 3)
                text = f["text"][start:start + width]
                return ("…" if start else "") + text + ("…" if start + width < len(f["text"]) else "")
    s = measure["fields"].get("summary")
    return s["text"][:width] if s else ""


def create_app():
    app = make_service("search")
    ballot = ServiceClient("ballot")

    corpus = []  # the ballot data does not change while the process runs (a release restarts it)

    def all_measures():
        if not corpus:
            listing = ballot.get("/measures")["measures"]
            corpus.extend(ballot.get(f"/measures/{m['id']}") for m in listing)
        return corpus

    @app.get("/search")
    def search():
        q = (request.args.get("q") or "").strip()[:100]
        topic = (request.args.get("topic") or "").strip().lower()
        try:
            measures = all_measures()
        except ServiceError:
            corpus.clear()  # never keep a half-loaded corpus
            abort(503, "Ballot data is unavailable.")
        topics = sorted({t for m in measures for t in m["topics"]})
        terms = _words(q)
        results = []
        for m in measures:
            if topic and topic not in m["topics"]:
                continue
            s = score(m, terms) if terms else 1
            if s:
                results.append({"id": m["id"], "number": m["number"], "title": m["title"],
                                "topics": m["topics"], "snippet": snippet(m, terms) if terms else
                                (m["fields"].get("summary") or {}).get("text", ""), "score": s})
        results.sort(key=lambda r: -r["score"])
        return jsonify(query=q, topic=topic or None, topics=topics, results=results)

    return app
