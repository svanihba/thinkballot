"""ask service: answers a voter's question about one measure, only from its official text.

Flow: fetch the measure from the ballot service -> answer model drafts points, each with a quote ->
the bias service checks every point -> verdict and final answer go back to the caller.
Question text is never logged.
"""

import re
import threading
import time
from collections import defaultdict, deque

from flask import abort, jsonify, request

from ... import ai, config
from ...servicekit import ServiceClient, ServiceError, make_service

FIELD_LABELS = {
    "measure_type": "Measure type",
    "summary": "Official summary",
    "yes_means": "What a YES vote means",
    "no_means": "What a NO vote means",
    "fiscal_effect": "Fiscal effect (Legislative Analyst)",
    "argument_for": "Official argument in favor",
    "argument_against": "Official argument against",
}

# Questions asking us to pick a side are answered with the same fixed reply, before any AI call.
HOW_TO_VOTE_RE = re.compile(
    r"\b(how should i vote|should i vote|which way should|what should i vote|vote (yes|no) or|"
    r"is (it|this|prop\w*) (good|bad)|do you (support|oppose|recommend|endorse)|"
    r"who is right|which side)\b", re.IGNORECASE)
HOW_TO_VOTE_REPLY = ("ThinkBallot never tells anyone how to vote. Read what a YES vote and a NO vote mean, "
                     "and both official arguments, then decide for yourself.")
MAX_QUESTION_CHARS = 300

ANSWER_SYSTEM = """You answer a voter's question about one California ballot measure for ThinkBallot,
a nonpartisan guide. Use ONLY the OFFICIAL SOURCE passages given. Never use outside knowledge.

Rules:
- Every point must include a "quote": an exact, word-for-word excerpt of the official source that
  supports the claim (copy it character for character; keep it under 40 words).
- Plain, neutral language a 16-year-old understands. No adjectives the source does not use.
- If the question is about effects, cover what YES means and what NO means, equally.
- Never say or hint how to vote.
- If the source does not answer the question, refuse.

Reply with JSON only:
{"refused": false, "points": [{"claim": "<one plain sentence>", "quote": "<exact excerpt>"}]}
or
{"refused": true, "reason": "<one sentence: what the official text does not cover>"}"""


def _stub_answer(user):
    """Offline stand-in: quote the first sentence of the first source passage."""
    passage = user.split("OFFICIAL SOURCE:\n", 1)[1].split("\n", 1)[1]
    first = re.split(r"(?<=\.)\s", passage.strip(), maxsplit=1)[0]
    return {"refused": False, "points": [{"claim": "The official text says: " + first, "quote": first}]}


class RateLimiter:
    """Allows `limit` requests per minute per key. In memory only; keys are never logged."""

    def __init__(self, limit):
        self.limit = limit
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key):
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True


def create_app():
    app = make_service("ask")
    ballot = ServiceClient("ballot")
    bias = ServiceClient("bias")
    limiter = RateLimiter(config.ASK_RATE_LIMIT_PER_MINUTE)

    @app.post("/ask")
    def ask():
        body = request.get_json(silent=True) or {}
        measure_id, question = body.get("measure_id"), body.get("question")
        if not isinstance(measure_id, str) or not isinstance(question, str) or not question.strip():
            abort(400, "measure_id and question are required")
        question = question.strip()[:MAX_QUESTION_CHARS]
        client_key = body.get("client") or request.remote_addr or "unknown"
        if not limiter.allow(client_key):
            abort(429, "Too many questions in a minute. Please wait a moment.")

        if HOW_TO_VOTE_RE.search(question):
            return jsonify(status="refused", reason=HOW_TO_VOTE_REPLY, points=[], findings=[])

        try:
            measure = ballot.get(f"/measures/{measure_id}")
        except ServiceError:
            abort(503, "Ballot data is unavailable right now.")
        if not measure:
            abort(404, "Unknown measure.")

        names = [n for n in FIELD_LABELS if n in measure["fields"]]
        sources = [measure["fields"][n]["text"] for n in names]
        passages = "\n\n".join(f"[{FIELD_LABELS[n]}]\n{t}" for n, t in zip(names, sources))
        user = f"MEASURE: {measure['title']}\n\nOFFICIAL SOURCE:\n{passages}\n\nQUESTION: {question}"

        try:
            draft = ai.chat_json(config.ANSWER_MODEL, ANSWER_SYSTEM, user, stub=_stub_answer)
        except ai.AIError:
            abort(503, "The question service is busy right now. Please try again in a minute.")
        if draft.get("refused"):
            reason = str(draft.get("reason") or "The official text does not answer this question.")
            return jsonify(status="refused", reason=reason, points=[], findings=[])

        points = [p for p in draft.get("points", []) if isinstance(p, dict)]
        try:
            result = bias.post("/check/answer", {"points": points, "sources": sources})
        except ServiceError:
            abort(503, "The Bias Buster check is unavailable, so no answer is shown.")

        for p in result["points"]:  # attach the field and link the quote came from
            name = names[p["source_index"]]
            p["source_label"] = FIELD_LABELS[name]
            p["source_url"] = measure["fields"][name]["source_url"]
        if result["verdict"] == "blocked":
            return jsonify(status="blocked", findings=result["findings"], points=[],
                           reason="Bias Buster could not confirm an answer from the official text.")
        return jsonify(status="answered", verdict=result["verdict"], points=result["points"],
                       findings=result["findings"])

    return app
