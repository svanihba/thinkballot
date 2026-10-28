"""Extractor: Orange County Registrar of Voters, local measures for November 3, 2026.

The "Contests Qualified for the Ballot" page lists every measure as "A – <jurisdiction>, <title>". The
"Assigned Measure Letters" page links one PDF per measure: that measure's section of the county voter
guide ("Ballot Measures-A"), which starts with the jurisdiction and title, then the ballot question,
then "What your vote means". The question and the title are cut from the PDF text; the contests page
says where the title ends. Anything unexpected raises ValueError.
"""

import re

from thinkballot.sourcetext import html_to_text

LETTERS_URL = "https://ocvote.gov/elections/assigned-measure-letters-november-3-2026"
CONTESTS_URL = "https://ocvote.gov/elections/contests-qualified-for-the-ballot-for-the-2026-general-election"
LABEL = "Orange County Registrar of Voters: Voter Information Guide, Measure {letter}"
COUNTY = "Orange"
CODE = "oc"

ENTRY_RE = re.compile(r"^([A-Z]{1,2}) – (.+)$")
HEAD_RE = re.compile(r"^Ballot Measures-(?P<letter>[A-Z]{1,2})\n(?P=letter)\nSection\n11\n(?P<head>.+?)\nWhat your vote means\n",
                     re.S)
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
    return m.group("letter"), jurisdiction, title, question


def extract(pages, field):
    for url in (LETTERS_URL, CONTESTS_URL):
        if url not in pages:
            raise ValueError(f"missing from the raw store: {url}")
    entries = contest_entries(pages[CONTESTS_URL]["body"].decode("utf-8"))
    by_letter = {}
    for url in measure_pdfs(pages[LETTERS_URL]["body"].decode("utf-8")):
        if url not in pages or "text" not in pages[url]:
            raise ValueError(f"measure PDF missing from the raw store: {url}")
        letter = pages[url]["text"].split("\n", 1)[0].removeprefix("Ballot Measures-")
        if letter not in entries or letter in by_letter:
            raise ValueError(f"{url}: measure {letter!r} is not listed once on the contests page")
        by_letter[letter] = url
    if set(by_letter) != set(entries):
        raise ValueError(f"no PDF for measures {sorted(set(entries) - set(by_letter))}")
    measures = []
    for letter in sorted(entries):
        url = by_letter[letter]
        got, jurisdiction, title, question = parse_section(pages[url]["text"], entries[letter])
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
