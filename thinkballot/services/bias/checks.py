"""The deterministic checks of the Bias Buster Engine. No AI here: plain, testable rules.

Each check returns a list of findings: {"check", "detail"}.
"""

import re
from pathlib import Path

LOADED_WORDS = [
    w.strip().lower()
    for w in (Path(__file__).with_name("loaded_words.txt")).read_text().splitlines()
    if w.strip() and not w.startswith("#")
]

# YES and NO text are "balanced" if the shorter is at least this share of the longer.
BALANCE_MIN_RATIO = 0.5

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "–": "-", "—": "-", " ": " "})


def normalize(text):
    """Lower-case, straighten quotes and dashes, collapse whitespace."""
    return re.sub(r"\s+", " ", (text or "").translate(_QUOTES)).strip().lower()


# A quote must be long enough to actually support a claim ("the" is in every source).
MIN_QUOTE_WORDS = 6

# Fixed, user-facing finding messages. Model-written text is never shown to voters.
MESSAGES = {
    "quote": "Removed a point whose quote could not be found word for word in the official text.",
    "number": "Removed a point with a number that does not appear in the official text.",
    "loaded_words": "Removed a point that used persuasive wording not found in its quote.",
    "balance": "YES and NO are not covered equally.",
    "ai_review": "The neutrality review reworded a point.",
}


def _padded(text):
    return " " + normalize(text) + " "


def source_index(quote, sources):
    """Index of the source that contains the quote word for word (whole words, parts in order), or None.

    '...' may join parts of one passage. Quotes shorter than MIN_QUOTE_WORDS count only if they are a
    whole source passage (e.g. "Legislative Statute.").
    """
    parts = [p.strip(" .,;:\"'") for p in re.split(r"\.\.\.|\u2026", normalize(quote))]
    parts = [p for p in parts if p]
    if not parts:
        return None
    # At least one unbroken part must be MIN_QUOTE_WORDS long, so "the ... the ... to" can't pass.
    longest = max(len(p.split()) for p in parts)
    for i, s in enumerate(sources):
        src = _padded(s)
        if longest < MIN_QUOTE_WORDS and normalize(quote).strip(" .") != normalize(s).strip(" ."):
            continue
        pos = 0
        for p in parts:
            m = re.search(r"(?<![\w$])" + re.escape(p) + r"(?!\w)", src[pos:])
            if not m:
                break
            pos += m.end()
        else:
            return i
    return None


def quote_found(quote, sources):
    return source_index(quote, sources) is not None


def text_on_page(text, page):
    """Seed verification: the whole field appears on its page word for word (any length)."""
    t = normalize(text)
    return bool(t) and re.search(r"(?<![\w$])" + re.escape(t) + r"(?!\w)", _padded(page)) is not None


_SCALES = ("thousand", "million", "billion", "trillion")


def numbers_in(text):
    """Numbers with their scale word: "$1,500" -> "1500", "$5 billion" -> "5 billion", "12.5%" -> "12.5"."""
    out = set()
    for m in re.finditer(r"\$?(\d[\d,]*(?:\.\d+)?)%?(?:\s+(" + "|".join(_SCALES) + r"))?", normalize(text)):
        num = m.group(1).replace(",", "").rstrip(".")
        out.add(f"{num} {m.group(2)}" if m.group(2) else num)
    return out


def check_quote(quote, sources):
    if not quote or not quote.strip() or not quote_found(quote, sources):
        return [{"check": "quote", "detail": MESSAGES["quote"]}]
    return []


def check_numbers(text, sources):
    allowed = set().union(*(numbers_in(s) for s in sources)) if sources else set()
    missing = numbers_in(text) - allowed
    return [{"check": "number", "detail": MESSAGES["number"], "value": n} for n in sorted(missing)]


def check_loaded_words(text, sources):
    """Flag persuasive words, unless the given source text itself uses them."""
    t = normalize(text)
    source_text = " ".join(normalize(s) for s in sources)
    findings = []
    for word in LOADED_WORDS:
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, t) and not re.search(pattern, source_text):
            findings.append({"check": "loaded_words", "detail": f'persuasive wording: "{word}"', "word": word})
    return findings


def check_balance(yes_text, no_text):
    """Both sides present, and neither dwarfs the other."""
    if not (yes_text or "").strip() or not (no_text or "").strip():
        return [{"check": "balance", "detail": "one side (YES or NO) is missing"}]
    a, b = len(yes_text.split()), len(no_text.split())
    if min(a, b) < BALANCE_MIN_RATIO * max(a, b):
        return [{"check": "balance", "detail": f"YES has {a} words and NO has {b}; lengths differ a lot"}]
    return []


def check_point(point, sources):
    """All deterministic checks for one claim of an answer.

    Persuasive words are allowed only if the point's OWN quote uses them, so an answer cannot borrow
    campaign wording from the official arguments and present it as neutral.
    """
    claim, quote = point.get("claim", ""), point.get("quote") or ""
    problems = check_quote(quote, sources)
    if problems:
        return problems
    words = [dict(f, detail=MESSAGES["loaded_words"]) for f in check_loaded_words(claim, [quote])]
    return check_numbers(claim, sources) + words
