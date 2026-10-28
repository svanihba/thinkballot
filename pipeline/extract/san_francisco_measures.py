"""Extractor: San Francisco Department of Elections, local measures for the November 3, 2026 election.

Two official sources:
- https://www.sf.gov/qualified-ballot-measures lists each measure as an accordion title "A - Charter
  Changes Affecting Various City Departments and Commissions" (letter and title).
- The City Attorney's ballot questions letter (PDF, linked from that page) gives each question as
  Proposition entitled "<title>": "<question>", without letters and not in letter order.

Questions are matched to letters by their titles. The two documents word a few titles slightly
differently ("Contributions to the Housing Fund" / "... Housing Trust Fund"), so a title matches the
page title sharing the most words; every match must be clear and one to one, or extraction fails.
The Regional Transit Measure is listed on the page but has no question in the letter, so it is left out.
"""

import re

from thinkballot.sourcetext import html_to_text

PAGE_URL = "https://www.sf.gov/qualified-ballot-measures"
PDF_URL = "https://api.sf.gov/documents/61682/Ballot_Questions_November_2026.pdf"
PAGE_LABEL = "San Francisco Department of Elections: Qualified ballot measures"
PDF_LABEL = "San Francisco City Attorney: November 3, 2026 Ballot Questions"
COUNTY = "San Francisco"
JURISDICTION = "City and County of San Francisco"
PAGE_HEADER_LINES = {"CITY AND COUNTY OF SAN FRANCISCO OFFICE OF THE CITY ATTORNEY", "Letter to John Arntz",
                     "August 7, 2026"}
MIN_MATCH = 0.75  # share of words two titles must have in common


def _words(title):
    return set(re.findall(r"[a-z0-9]+", title.lower().replace("’", "'")))


def _similarity(a, b):
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb)


def page_measures(raw):
    """[(letter, title)] in page order, from the accordion titles."""
    titles = [" ".join(html_to_text(t).split())
              for t in re.findall(r'<h3[^>]*data-testid="accordion-title"[^>]*>(.*?)</h3>', raw, re.S)]
    measures = []
    for t in titles:
        m = re.fullmatch(r"([A-Z]{1,3}) - (.+)", t)
        if m:
            measures.append(m.groups())
    return measures


def letter_questions(text):
    """[(title, question)] from the City Attorney's letter, in the letter's order."""
    if "November 3, 2026 Ballot Questions" not in text:
        raise ValueError("the PDF is not the November 3, 2026 ballot questions letter")
    m = re.search(r"Please find below the ballot questions[^\n]*\n(.*?)\nVery truly yours", text, re.S)
    if not m:
        raise ValueError("ballot questions not found in the letter")
    lines = [line for line in m.group(1).split("\n") if line.strip() not in PAGE_HEADER_LINES]
    body = " ".join(lines)
    entries = re.split(r"(?=Proposition entitled “)", body)
    if entries[0].strip():
        raise ValueError(f"unexpected text before the first question: {entries[0][:80]}")
    out = []
    for entry in entries[1:]:
        e = re.fullmatch(r"Proposition entitled “([^”]+)”: “([^”]+\?)”\s*", entry)
        if not e:
            raise ValueError(f"unexpected question layout: {entry[:120]}")
        out.append(e.groups())
    return out


def extract(pages, field):
    for url in (PAGE_URL, PDF_URL):
        if url not in pages:
            raise ValueError(f"missing from the raw store: {url}")
    listed = page_measures(pages[PAGE_URL]["body"].decode("utf-8"))
    letters = [(letter, title) for letter, title in listed if letter != "RTM"]
    if not letters:
        raise ValueError("no lettered measures on the qualified ballot measures page")
    questions = letter_questions(pages[PDF_URL]["text"])
    if len(questions) != len(letters):
        raise ValueError(f"{len(letters)} lettered measures on the page but {len(questions)} questions in the letter")
    by_letter = {}
    for pdf_title, question in questions:
        scores = sorted(((_similarity(pdf_title, title), letter, title) for letter, title in letters), reverse=True)
        best, runner_up = scores[0], scores[1] if len(scores) > 1 else (0,)
        if best[0] < MIN_MATCH or runner_up[0] >= best[0]:
            raise ValueError(f"no clear page title for the question titled {pdf_title!r}")
        if best[1] in by_letter:
            raise ValueError(f"two questions match Measure {best[1]}")
        by_letter[best[1]] = (best[2], question)
    measures = []
    for letter, _ in letters:
        title, question = by_letter[letter]
        measures.append({
            "id": f"local-sf-{letter.lower()}", "number": letter,
            "title": field(title, PAGE_URL, PAGE_LABEL),
            "jurisdiction": {"level": "local", "county": COUNTY, "name": JURISDICTION},
            "topics": [], "documents": [], "notes": [], "arguments_url": None,
            "fields": {"ballot_question": field(question, PDF_URL, PDF_LABEL)},
        })
    return measures
