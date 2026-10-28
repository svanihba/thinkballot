"""Extractor: Orange County Registrar of Voters, local measures for November 3, 2026.

The "Contests Qualified for the Ballot" page lists every measure as "A – <jurisdiction>, <title>". The
"Assigned Measure Letters" page links one PDF per measure: that measure's section of the county voter
guide ("Ballot Measures-A"), which starts with the jurisdiction and title, then the ballot question,
then "What your vote means". The question and the title are cut from the PDF text; the contests page
says where the title ends. Anything unexpected raises ValueError, except a question whose text came out
of the PDF damaged (spaces lost): that measure is skipped, logged and listed in SKIPPED.
"""

import re

from thinkballot.sourcetext import html_to_text

LETTERS_URL = "https://ocvote.gov/elections/assigned-measure-letters-november-3-2026"
CONTESTS_URL = "https://ocvote.gov/elections/contests-qualified-for-the-ballot-for-the-2026-general-election"
LABEL = "Orange County Registrar of Voters: Voter Information Guide, Measure {letter}"
COUNTY = "Orange"
CODE = "oc"

ENTRY_RE = re.compile(r"^([A-Z]{1,2}) – (.+)$")
# The page header ("Ballot Measures-A", section number 11, the big letter) comes out of pdftotext in a few
# orders; all of them are accepted, nothing else is.
HEAD_RE = re.compile(r"^Ballot Measures-(?P<letter>[A-Z]{1,2})(?: 11)?\n(?:Section\n)?(?P=letter)[ \n]"
                     r"(?P<head>.+?)\nWhat your vote means\n", re.S)
LETTER_RE = re.compile(r"^Ballot Measures-([A-Z]{1,2})\b")
SQUASHED = 30  # a "word" this long is a line whose spaces the PDF text lost
SKIPPED = []  # measures left out because their question is unreadable in the PDF text: {letter, jurisdiction, url, reason}


class Unreadable(ValueError):
    """The section has the expected layout, but its question text came out of the PDF damaged."""
_FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def _fold(words):
    return " ".join(words).translate(_FOLD).lower()


def contest_entries(raw):
    """{letter: "jurisdiction, title"} from the contests page (an entry can wrap onto a second line)."""
    lines = html_to_text(raw).splitlines()
    try:
        start, end = lines.index("Measures"), lines.index("Contact Us")
    except ValueError:
        raise ValueError("contests page: no Measures list") from None
    entries, last = {}, None
    for line in (" ".join(x.split()) for x in lines[start + 1:end]):
        if not line:
            continue
        m = ENTRY_RE.match(line)
        if m:
            last = m.group(1)
            if last in entries:
                raise ValueError(f"contests page: measure {last} listed twice")
            entries[last] = m.group(2)
        elif last:
            entries[last] += " " + line
        else:
            raise ValueError(f"contests page: unexpected line {line!r}")
    if not entries:
        raise ValueError("contests page: no measures")
    return entries


def measure_pdfs(raw):
    """PDF URLs linked from the assigned-letters page, in page order."""
    links = re.findall(r'href="(/sites/default/files/[^"]+\.pdf)"', raw)
    return ["https://ocvote.gov" + link for link in links]


def parse_section(text, entry):
    """(jurisdiction, title, question) from one measure's PDF text, given its contests-page entry."""
    m = HEAD_RE.match(text)
    if not m:
        raise ValueError(f"unexpected start of section: {text[:80]!r}")
    words, want = m.group("head").split(), entry.split()
    head = words[:len(want)]
    if _fold(head) != _fold(want):
        raise ValueError(f"section {m.group('letter')} does not start with {entry!r}")
    jurisdiction, _, title = " ".join(head).partition(", ")
    question = " ".join(words[len(want):])
    if not (jurisdiction and title) or not question.endswith("?") or len(question.split()) < 8:
        raise ValueError(f"section {m.group('letter')}: no ballot question after the title")
    if any(len(w) > SQUASHED for w in question.split()):
        raise Unreadable(f"section {m.group('letter')}: the PDF text lost the spaces in part of the question")
    return m.group("letter"), jurisdiction, title, question


def _spaced(page):
    """The -raw text with the ballot question taken from the layout reading instead (see
    pdf_second_reading in the source file): the question runs from the line after the title to the
    first "?", and the layout reading keeps its spaces and line-end hyphens."""
    raw, layout = page["text"], page["layout_text"]
    q_start = next((i for i, line in enumerate(layout.split("\n")) if line.startswith("To ") or
                    line.startswith("Shall ")), None)
    if q_start is None:
        raise Unreadable("layout reading: no ballot question found")
    lines = []
    for line in layout.split("\n")[q_start:]:
        if lines and re.search(r"[A-Za-z]-$", lines[-1]) and line[:1].isalpha():
            lines[-1] += line
        else:
            lines.append(line)
        if line.endswith("?"):
            break
    question = " ".join(lines)
    head_end = raw.index(question.split()[0] + " " + question.split()[1])
    return raw[:head_end] + question + raw[raw.index("\nWhat your vote means\n"):]


def extract(pages, field):
    for url in (LETTERS_URL, CONTESTS_URL):
        if url not in pages:
            raise ValueError(f"missing from the raw store: {url}")
    entries = contest_entries(pages[CONTESTS_URL]["body"].decode("utf-8"))
    by_letter = {}
    for url in measure_pdfs(pages[LETTERS_URL]["body"].decode("utf-8")):
        if url not in pages or "text" not in pages[url]:
            raise ValueError(f"measure PDF missing from the raw store: {url}")
        found = LETTER_RE.match(pages[url]["text"])
        letter = found.group(1) if found else None
        if letter not in entries or letter in by_letter:
            raise ValueError(f"{url}: measure {letter!r} is not listed once on the contests page")
        by_letter[letter] = url
    if set(by_letter) != set(entries):
        raise ValueError(f"no PDF for measures {sorted(set(entries) - set(by_letter))}")
    measures = []
    SKIPPED.clear()
    for letter in sorted(entries):
        url = by_letter[letter]
        try:
            try:
                _, jurisdiction, title, question = parse_section(pages[url]["text"], entries[letter])
            except Unreadable:
                if "layout_text" not in pages[url]:
                    raise
                _, jurisdiction, title, question = parse_section(_spaced(pages[url]), entries[letter])
        except Unreadable as exc:
            SKIPPED.append({"letter": letter, "jurisdiction": entries[letter].partition(", ")[0], "url": url,
                            "reason": str(exc)})
            print(f"orange_measures: SKIPPED measure {letter} ({url}): {exc}")
            continue
        label = LABEL.format(letter=letter)
        measures.append({
            "id": f"local-{CODE}-{letter.lower()}", "number": letter,
            "title": field(title, url, label),
            "jurisdiction": {"level": "local", "county": COUNTY, "name": jurisdiction},
            "topics": [], "notes": [], "arguments_url": None,
            "documents": [{"label": f"Measure {letter}: county voter guide section (PDF)",
                           "url": url}],
            "fields": {
                "district": field(jurisdiction, url, label),
                "ballot_question": field(question, url, label),
            },
        })
    return measures
