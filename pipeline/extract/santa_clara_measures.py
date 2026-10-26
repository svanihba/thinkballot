"""Extractor: Santa Clara County Registrar of Voters, "List of Local Measures" page.

Each measure is a <table> whose <caption> has four lines (jurisdiction, "Measure X", title, vote
threshold) and whose first cell is the full ballot question. The official PDFs (impartial analysis,
arguments, rebuttals) linked after the table are kept as documents, not parsed.
"""

import re

from thinkballot.sourcetext import html_to_text

URL = "https://vote.santaclaracounty.gov/list-local-measures-4"
LABEL = "Santa Clara County Registrar of Voters: List of Local Measures"
COUNTY = "Santa Clara"


def _text(fragment):
    return " ".join(html_to_text(fragment).split())


def extract(pages, field):
    if URL not in pages:
        raise ValueError(f"missing from the raw store: {URL}")
    raw = pages[URL]["body"].decode("utf-8")
    chunks = re.split(r'(?=<table class="align-table-left)', raw)[1:]
    measures = []
    for chunk in chunks:
        caption = re.search(r"<caption>(.*?)</caption>", chunk, re.S)
        if not caption:
            continue
        lines = [_text(s) for s in re.findall(r"<strong>(.*?)</strong>", caption.group(1), re.S)]
        lines = [line for line in lines if line]
        if len(lines) < 4 or not lines[1].startswith("Measure "):
            raise ValueError(f"unexpected caption: {lines}")
        district, letter_line, title, threshold = lines[0], lines[1], lines[2], lines[3]
        letter = letter_line.split(" ", 1)[1].strip()
        question = _text(re.search(r"<td>(.*?)</td>", chunk, re.S).group(1))
        after_table = chunk.split("</table>", 1)[1]
        documents = [{"label": _text(label), "url": href.replace("&amp;", "&")}
                     for href, label in re.findall(r'<a href="(https://files\.santaclaracounty\.gov/[^"]+)"[^>]*>(.*?)</a>',
                                                   after_table, re.S)]
        none_filed = [_text(s) for s in re.findall(r"(Primary Argument [^<]*\(none filed\))", after_table)]
        measures.append({
            "id": f"local-sc-{letter.lower()}", "number": letter,
            "title": field(title, URL, LABEL),
            "jurisdiction": {"level": "local", "county": COUNTY, "name": district},
            "topics": [], "documents": documents, "notes": none_filed, "arguments_url": None,
            "fields": {
                "measure_type": field(threshold, URL, LABEL),
                "district": field(district, URL, LABEL),
                "ballot_question": field(question, URL, LABEL),
            },
        })
    return measures
