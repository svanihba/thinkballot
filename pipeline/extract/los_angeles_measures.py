"""Extractor: Los Angeles County Registrar-Recorder/County Clerk, "Measures Appearing on the Ballot" (PDF).

The county and local sections list, per jurisdiction, a header line ("CITY OF BURBANK – (3)"), the
vote needed ("VOTE PASSAGE – Majority Vote 50%+1"), then each measure: its letter in a left column and
the ballot question followed by "Supporters: ... Opponents: ...".

The letter column only lines up with its measure in pdftotext's layout mode, so the layout text is
used to find the structure (letter, jurisdiction, vote needed, where each question starts and ends).
The field text itself is then cut from the run.py PDF text (pages[url]["text"]), which is what the
seed verifies against. Anything unexpected raises ValueError.
"""

import re
import subprocess

URL = "https://content.lavote.gov/docs/rrcc/documents/final-measures-appearing-on-the-ballot-9-22-2026.pdf"
LABEL = "Los Angeles County Registrar-Recorder/County Clerk: Measures Appearing on the Ballot, November 3, 2026"
COUNTY = "Los Angeles"
CODE = "la"

SKIP_RE = re.compile(r"^(\d+ ?\| ?P ?a ?g ?e|LOCAL JURISDICTION MEASURES – \(\d+\)( Continued)?|Rev\. [\d/]+)$")
HEADER_RE = re.compile(r"^(?P<name>[A-Z][A-Z .'’-]+?)\s*(?:Continued)?\s*– \((?P<count>\d+)\)$")
PASSAGE_RE = re.compile(r"^VOTE PASSAGE – (?P<threshold>.+)$")
MEASURE_RE = re.compile(r"^ ?(?P<letter>[A-Z]{1,3})\s{2,}(?P<text>\S.*)$")
SMALL_WORDS = {"of", "and", "the"}


def layout_text(body):
    out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=body,
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def display_name(name):
    """'CITY OF EL SEGUNDO' -> 'City of El Segundo' (case only; the words are the county's)."""
    words = name.split()
    return " ".join(w.lower() if i and w.lower() in SMALL_WORDS else w.capitalize() for i, w in enumerate(words))


def parse_layout(layout):
    """[{letter, jurisdiction, threshold, text}] in document order, from the county section on."""
    start = layout.find("COUNTY MEASURES – (")
    if start < 0:
        raise ValueError("no COUNTY MEASURES section")
    measures, jurisdiction, threshold, current = [], None, None, None
    for raw_line in layout[start:].splitlines()[1:]:
        line = raw_line.strip()
        if not line or SKIP_RE.match(line):
            continue
        header, passage, measure = HEADER_RE.match(line), PASSAGE_RE.match(line), MEASURE_RE.match(raw_line)
        if header:
            jurisdiction, threshold, current = header.group("name").strip(), None, None
        elif passage:
            threshold, current = passage.group("threshold").strip(), None
        elif measure:
            if not (jurisdiction and threshold):
                raise ValueError(f"measure {measure.group('letter')} before its jurisdiction and vote needed")
            current = {"letter": measure.group("letter"), "jurisdiction": jurisdiction,
                       "threshold": threshold, "lines": [measure.group("text")]}
            measures.append(current)
        elif raw_line.startswith(" ") and current:
            current["lines"].append(line)
        else:
            raise ValueError(f"unexpected line: {line!r}")
    for m in measures:
        m["text"] = " ".join(" ".join(m.pop("lines")).split())
    # The PDF states how many county and local measures there are; every one must have been found.
    stated = sum(int(n) for n in re.findall(r"^\s*(?:COUNTY|LOCAL JURISDICTION) MEASURES – \((\d+)\)$", layout, re.M))
    if stated != len(measures):
        raise ValueError(f"the PDF lists {stated} county and local measures, found {len(measures)}")
    return measures


def find_verbatim(snippet, text, once=True):
    """The exact span of `text` matching `snippet`, allowing for line-break hyphens that one of the two
    pdftotext modes kept and the other dropped. Raises if it is missing, or (with once) repeated."""
    words = snippet.split()
    parts = []
    for i, w in enumerate(words):
        if i:
            parts.append(r"\s*" if words[i - 1].endswith("-") else r"\s+")
        parts.append(re.escape(w[:-1]) + r"-?" if w.endswith("-") and len(w) > 1 else re.escape(w))
    hits = list(re.finditer("".join(parts), text))
    if not hits or (once and len(hits) > 1):
        raise ValueError(f"found {len(hits)} times in the PDF text: {snippet[:80]!r}")
    return " ".join(hits[0].group(0).split())


def parse(layout, text):
    measures, seen = [], set()
    for m in parse_layout(layout):
        if m["text"].count("Supporters:") != 1:
            raise ValueError(f"measure {m['letter']}: expected one 'Supporters:' in {m['text'][:80]!r}")
        question = m["text"].split("Supporters:")[0].strip()
        if len(question.split()) < 8 or "?" not in question:
            raise ValueError(f"measure {m['letter']}: no ballot question in {question!r}")
        if m["letter"] in seen:
            raise ValueError(f"measure letter {m['letter']} appears twice")
        seen.add(m["letter"])
        name = display_name(m["jurisdiction"])
        measures.append({"letter": m["letter"], "name": name,
                         "district": find_verbatim(m["jurisdiction"], text, once=False),
                         "threshold": find_verbatim(m["threshold"], text, once=False),
                         "question": find_verbatim(question, text)})
    return measures


def extract(pages, field):
    if URL not in pages:
        raise ValueError(f"missing from the raw store: {URL}")
    page = pages[URL]
    if "text" not in page:
        raise ValueError("expected a PDF")
    out = []
    for m in parse(layout_text(page["body"]), page["text"]):
        out.append({
            "id": f"local-{CODE}-{m['letter'].lower()}", "number": m["letter"],
            "title": field(m["name"], URL, LABEL),
            "jurisdiction": {"level": "local", "county": COUNTY, "name": m["name"]},
            "topics": [], "documents": [], "notes": [], "arguments_url": None,
            "fields": {
                "measure_type": field(m["threshold"], URL, LABEL),
                "district": field(m["district"], URL, LABEL),
                "ballot_question": field(m["question"], URL, LABEL),
            },
        })
    return out
