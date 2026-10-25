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
_NUMBER_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")


def normalize(text):
    """Lower-case, straighten quotes and dashes, collapse whitespace."""
    return re.sub(r"\s+", " ", (text or "").translate(_QUOTES)).strip().lower()


def source_index(quote, sources):
    """Index of the source that contains the quote word for word, or None.

    '...' may join parts of one passage.
    """
    parts = [p.strip(" .,;:\"'") for p in re.split(r"\.\.\.|…", normalize(quote))]
    parts = [p for p in parts if p]
    if not parts:
        return None
    for i, s in enumerate(sources):
        if all(p in normalize(s) for p in parts):
            return i
    return None


def quote_found(quote, sources):
    return source_index(quote, sources) is not None


def numbers_in(text):
    """Numbers as plain digits: "$1,500" -> "1500", "12.5%" -> "12.5"."""
    return {n.strip("$%").replace(",", "").rstrip(".") for n in _NUMBER_RE.findall(text or "")}


def check_quote(quote, sources):
    if not quote or not quote.strip():
        return [{"check": "quote", "detail": "no quote from the official text supports this"}]
    if not quote_found(quote, sources):
        return [{"check": "quote", "detail": f'quote not found in the official text: "{quote}"'}]
    return []


def check_numbers(text, sources):
    allowed = set().union(*(numbers_in(s) for s in sources)) if sources else set()
    return [{"check": "number", "detail": f"number {n} does not appear in the official text"}
            for n in sorted(numbers_in(text) - allowed)]


def check_loaded_words(text, sources):
    """Flag persuasive words, unless the official text itself uses them."""
    t = normalize(text)
    source_text = " ".join(normalize(s) for s in sources)
    findings = []
    for word in LOADED_WORDS:
        pattern = r"\b" + re.escape(word) + r"\b"
        if re.search(pattern, t) and not re.search(pattern, source_text):
            findings.append({"check": "loaded_words", "detail": f'persuasive wording: "{word}"'})
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
    """All deterministic checks for one claim of an answer."""
    claim = point.get("claim", "")
    return (check_quote(point.get("quote"), sources)
            + check_numbers(claim, sources)
            + check_loaded_words(claim, sources))
