"""ask service: answers a voter's question about one measure, only from its official text.

Flow: fetch the measure from the ballot service -> answer model drafts points, each with a quote ->
the bias service checks every point -> verdict and final answer go back to the caller.
Question text is never logged. Answers to the fixed suggested questions are prepared in advance
(cache.py) and re-checked by Bias Buster each time they are used; typed questions are never stored.
"""

import re
import time

from flask import abort, jsonify, request

from ... import ai, config, ratelimit
from ...servicekit import ServiceClient, ServiceError, make_service
from . import cache

FIELD_LABELS = {
    "measure_type": "Measure type",
    "summary": "Official summary",
    "yes_means": "What a YES vote means",
    "no_means": "What a NO vote means",
    "fiscal_effect": "Fiscal effect (Legislative Analyst)",
    "argument_for": "Official argument in favor",
    "argument_against": "Official argument against",
    "supporters": "Supporters",
    "opponents": "Opponents",
    "analysis": "Legislative Analyst's analysis",
    "district": "Jurisdiction",
    "ballot_question": "Ballot question (as printed on the ballot)",
}

# Questions asking us to pick a side are answered with the same fixed reply, before any AI call.
HOW_TO_VOTE_RE = re.compile(
    r"\b(how should i vote|should i vote|which way should|what should i vote|vote (yes|no) or|"
    r"is (it|this|prop\w*) (good|bad)|do you (support|oppose|recommend|endorse)|"
    r"who is right|which side)\b", re.IGNORECASE)
HOW_TO_VOTE_REPLY = ("ThinkBallot never tells anyone how to vote. Read what a YES vote and a NO vote mean, "
                     "and both official arguments, then decide for yourself.")
NOT_COVERED_REPLY = ("The official guide doesn't answer that question, so ThinkBallot won't guess. "
                     "Try asking about what a YES or NO vote does, the cost, or who supports or opposes it.")
MAX_QUESTION_CHARS = 300
MEASURE_ID_RE = re.compile(r"^(prop|local)-[a-z0-9-]{1,24}$")

ANSWER_SYSTEM = """You answer a voter's question about one California ballot measure for ThinkBallot,
a nonpartisan guide. Use ONLY the OFFICIAL SOURCE passages given. Never use outside knowledge.

Rules:
- Every point must include a "quote": an exact, word-for-word excerpt of the official source that
  supports the claim (copy it character for character; keep it under 40 words).
- Plain, neutral language a 16-year-old understands. No adjectives the source does not use.
- If the question is about effects, cover what YES means and what NO means, equally.
- A measure's own statements of its purpose or expected benefits (for example a ballot question's
  "to prevent service cuts" or "to improve safety") are claims, not facts: attribute them, e.g. "The
  ballot question says the measure would ...". Never state a goal or prediction as a fact.
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


def source_text(measure):
    """(field names, source passages, the text sent to the answer model before the question)."""
    names = [n for n in FIELD_LABELS if n in measure["fields"]]
    sources = [measure["fields"][n]["text"] for n in names]
    passages = "\n\n".join(f"[{FIELD_LABELS[n]}]\n{t}" for n, t in zip(names, sources))
    return names, sources, f"MEASURE: {measure['title']}\n\nOFFICIAL SOURCE:\n{passages}"


def _with_sources(points, measure, names):
    """Attach the field and link each quote came from."""
    return [dict(p, source_label=FIELD_LABELS[names[p["source_index"]]],
                 source_url=measure["fields"][names[p["source_index"]]]["source_url"]) for p in points]


def _cache_key(measure, question):
    """None for a typed question: only the fixed suggested questions are ever cached."""
    return cache.make_key(measure["id"], question, ANSWER_SYSTEM + "\n" + source_text(measure)[2])


def load_measure(ballot, measure_id):
    try:
        measure = ballot.get(f"/measures/{measure_id}")
    except ServiceError:
        abort(503, "Ballot data is unavailable right now.")
    if not measure:
        abort(404, "Unknown measure.")
    return measure


def prepared_answer(measure, question, bias):
    """The answer prepared in advance for a suggested question, re-checked word for word against the
    current official text (no AI). None if there is none or it no longer passes."""
    key = _cache_key(measure, question)
    entry = cache.get(key) if key else None
    if not entry:
        return None
    result, bias_version, prepared = entry
    if result["status"] == "answered":
        names, sources, _ = source_text(measure)
        try:
            check = bias.post("/check/answer", {"points": result["points"], "sources": sources,
                                                "ai_review": False})
        except ServiceError:
            return None
        if (check.get("bias_version") != bias_version or check["verdict"] != "pass"
                or len(check["points"]) != len(result["points"])):
            return None
        result = dict(result, points=_with_sources(check["points"], measure, names))
    return dict(result, prepared=prepared)


def live_answer(measure, question, bias):
    """Ask the answer model, then Bias Buster. Answers to suggested questions are kept for next time."""
    names, sources, text = source_text(measure)
    user = f"{text}\n\nQUESTION: {question}"
    key = _cache_key(measure, question)

    deadline = time.monotonic() + config.ASK_BUDGET_SECONDS
    try:  # the answer may use at most ~60% of the budget, leaving time for the Bias Buster review
        draft = ai.chat_json(config.ANSWER_MODEL, ANSWER_SYSTEM, user, stub=_stub_answer,
                             deadline=time.monotonic() + 0.6 * config.ASK_BUDGET_SECONDS)
    except ai.AIError:
        abort(503, "The question service is busy right now. Please try again in a minute.")
    if draft.get("refused"):
        # Fixed wording: the model's own explanation is never shown to voters.
        result = {"status": "refused", "reason": NOT_COVERED_REPLY, "points": [], "findings": []}
        if key:
            cache.put(key, measure["id"], "", result)  # no Bias Buster check runs on a refusal
        return result

    points = [p for p in draft.get("points", []) if isinstance(p, dict)]
    try:
        check = bias.post("/check/answer", {"points": points, "sources": sources,
                                            "budget_seconds": max(deadline - time.monotonic(), 1)})
    except ServiceError:
        abort(503, "The Bias Buster check is unavailable, so no answer is shown.")
    if check["verdict"] == "blocked":  # never cached
        return {"status": "blocked", "findings": check["findings"], "points": [],
                "reason": "Bias Buster could not confirm an answer from the official text."}
    if key:
        cache.put(key, measure["id"], check["bias_version"], {
            "status": "answered", "verdict": check["verdict"], "findings": check["findings"],
            "points": [{"claim": p["claim"], "quote": p["quote"]} for p in check["points"]]})
    return {"status": "answered", "verdict": check["verdict"], "findings": check["findings"],
            "points": _with_sources(check["points"], measure, names)}


def create_app():
    app = make_service("ask", internal=True)
    ballot = ServiceClient("ballot")
    bias = ServiceClient("bias")

    @app.post("/ask")
    def ask():
        body = request.get_json(silent=True) or {}
        measure_id, question = body.get("measure_id"), body.get("question")
        if not isinstance(measure_id, str) or not MEASURE_ID_RE.match(measure_id):
            abort(400, "unknown measure")
        if not isinstance(question, str) or not question.strip():
            abort(400, "question is required")
        question = question.strip()[:MAX_QUESTION_CHARS]
        client = ratelimit.client_key(body.get("client") or request.remote_addr)
        if not ratelimit.allow("ask", client, config.ASK_LIMITS_PER_CLIENT):
            abort(429, "Too many questions. Please wait a moment.")

        if HOW_TO_VOTE_RE.search(question):
            return jsonify(status="refused", reason=HOW_TO_VOTE_REPLY, points=[], findings=[])
        measure = load_measure(ballot, measure_id)
        # A prepared answer makes no AI call, so it counts only against the per-client limit above.
        result = prepared_answer(measure, question, bias)
        if result:
            return jsonify(result)
        if not ratelimit.allow("ask", None, config.ASK_LIMITS_SITEWIDE):  # protects the AI quota
            abort(429, "ThinkBallot is answering a lot of questions right now. Please try again later.")
        return jsonify(live_answer(measure, question, bias))

    return app
