"""Bias Buster Engine: decides whether a text may be shown to voters.

Modes:
- verify:  official text we copied must appear word for word in its source page (catches copying errors).
- audit:   official text is checked and findings are recorded, but the text is never changed.
- enforce: ThinkBallot- or AI-written text must pass; failing parts are removed, or the whole is blocked.

Deterministic checks run first. In enforce mode an AI review may then suggest minimal edits, and the
edited text goes through the deterministic checks again, so the AI is never the only guard.
"""

import json
import logging

from ... import ai, config
from . import checks

log = logging.getLogger("thinkballot.bias")

REVIEW_SYSTEM = """You are the neutrality reviewer for ThinkBallot, a nonpartisan California ballot guide.
You receive OFFICIAL SOURCE passages and an ANSWER made of points. Each point has a "claim" and the
"quote" from the official source that supports it.

Check every point against this rubric:
1. Claims beyond the source: the claim says something the quote does not support.
2. One-sided framing: presents only benefits or only costs where the source gives both.
3. Implied recommendation: hints how to vote, or that one side is right.
4. Emotional or loaded wording, or adjectives not used by the source.
5. Missing side: a question about effects is answered for YES only or NO only.

Fix problems with the smallest possible edit, using the source's own wording. Never add facts, numbers
or quotes that are not in the source. Remove a point you cannot fix. Keep each point's quote exactly as
given, unless you remove the point.

Reply with JSON only:
{"findings": [{"check": "ai_review", "detail": "<what was wrong and what you changed>"}],
 "points": [{"claim": "...", "quote": "..."}]}"""


def _stub_review(user):
    """Offline stand-in: approve the points as they are."""
    return {"findings": [], "points": json.loads(user.split("ANSWER:\n", 1)[1])["points"]}


def ai_review(points, sources):
    points = [{"claim": p["claim"], "quote": p["quote"]} for p in points]
    user = ("OFFICIAL SOURCE:\n" + "\n---\n".join(sources)
            + "\n\nANSWER:\n" + json.dumps({"points": points}, ensure_ascii=False))
    reply = ai.chat_json(config.REVIEW_MODEL, REVIEW_SYSTEM, user, stub=_stub_review)
    new_points = [p for p in reply.get("points", []) if isinstance(p, dict) and p.get("claim")]
    findings = [{"check": "ai_review", "detail": str(f.get("detail", ""))}
                for f in reply.get("findings", []) if isinstance(f, dict)]
    return new_points, findings


def _keep_passing(points, sources, findings):
    kept = []
    for p in points:
        problems = checks.check_point(p, sources)
        if problems:
            findings.extend(dict(f, action="removed") for f in problems)
        else:
            kept.append({"claim": p["claim"], "quote": p["quote"],
                         "source_index": checks.source_index(p["quote"], sources)})
    return kept


def check_answer(points, sources, use_ai=True):
    """Enforce mode for an AI answer made of {claim, quote} points."""
    findings = []
    kept = _keep_passing(points, sources, findings)
    if use_ai and kept:
        try:
            reviewed, ai_findings = ai_review(kept, sources)
        except ai.AIError as exc:
            log.warning("bias ai review failed: %s", exc)
            return {"verdict": "blocked", "points": [], "findings": findings + [
                {"check": "ai_review", "detail": "the neutrality review could not run, so the answer is held back",
                 "action": "blocked"}]}
        findings.extend(dict(f, action="edited") for f in ai_findings)
        kept = _keep_passing(reviewed, sources, findings)
    if not kept:
        verdict = "blocked"
    elif findings:
        verdict = "revised"
    else:
        verdict = "pass"
    return {"verdict": verdict, "points": kept, "findings": findings}


def check_text(text, sources, mode, sides=None):
    """verify / audit / enforce for a single piece of text."""
    if mode == "verify":
        findings = [] if checks.quote_found(text, sources) else [
            {"check": "quote", "detail": "text does not appear word for word on its source page"}]
        return {"verdict": "fail" if findings else "pass", "text": text, "findings": findings}

    # In audit mode the source is the text itself, so loaded words are flagged without the source exemption.
    word_sources = [] if mode == "audit" else sources
    findings = checks.check_numbers(text, sources) + checks.check_loaded_words(text, word_sources)
    if sides:
        findings += checks.check_balance(sides.get("yes"), sides.get("no"))
    if mode == "audit":  # official text: record, never change
        return {"verdict": "flagged" if findings else "pass", "text": text, "findings": findings}
    return {"verdict": "blocked" if findings else "pass", "text": text if not findings else None,
            "findings": findings}
