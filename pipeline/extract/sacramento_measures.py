"""Extractor: Sacramento County Voter Registration and Elections, "Current Measure Information" page.

The page lists each measure of the November 3, 2026 election as an accordion item: the button reads
"Measure D: Natomas Unified School District", and the body starts with the vote needed ("55% Vote
Required"; city measures have none), then the ballot question, then the impartial analysis, full text
and arguments (kept on the page, not parsed). Items marked "WITHDRAWN --" are not on the ballot.
"""

import re

from thinkballot.sourcetext import html_to_text

URL = "https://elections.saccounty.gov/content/vre/us/en/election-information/current-measure-information.html"
LABEL = "Sacramento County Voter Registration and Elections: Current Measure Information"
COUNTY = "Sacramento"


def _text(fragment):
    return " ".join(html_to_text(fragment).split())


def extract(pages, field):
    if URL not in pages:
        raise ValueError(f"missing from the raw store: {URL}")
    raw = pages[URL]["body"].decode("utf-8")
    if "November 3, 2026, General Election" not in raw:
        raise ValueError("the page is not for the November 3, 2026 General Election")
    items = re.findall(r'<button class="accordion-button[^"]*"[^>]*>(.*?)</button>(.*?)(?=<div class="accordion-item|\Z)',
                       raw, re.S)
    if not items:
        raise ValueError("no measures found")
    measures, seen = [], set()
    for button, body in items:
        heading = _text(button)
        if heading.startswith("WITHDRAWN -- Measure "):
            continue
        m = re.fullmatch(r"Measure ([A-Z]{1,3}): (.+)", heading)
        if not m:
            raise ValueError(f"unexpected measure heading: {heading}")
        letter, district = m.groups()
        paras = [_text(p) for p in re.findall(r"<p>(.*?)</p>", body, re.S)]
        paras = [p for p in paras if p]
        threshold = None
        if paras and re.fullmatch(r"(\d+%|\d+/\d+|Majority) Vote Required", paras[0]):
            threshold = paras.pop(0)
        if len(paras) < 2 or not paras[0].endswith("?") or not paras[1].startswith("Impartial Analysis"):
            raise ValueError(f"Measure {letter}: no ballot question followed by the impartial analysis")
        question = paras[0]
        mid = f"local-sa-{letter.lower()}"
        if mid in seen:
            raise ValueError(f"Measure {letter} appears twice")
        seen.add(mid)
        fields = {"district": field(district, URL, LABEL), "ballot_question": field(question, URL, LABEL)}
        if threshold:
            fields = {"measure_type": field(threshold, URL, LABEL), **fields}
        measures.append({
            "id": mid, "number": letter,
            "title": field(district, URL, LABEL),
            "jurisdiction": {"level": "local", "county": COUNTY, "name": district},
            "topics": [], "documents": [], "notes": [], "arguments_url": None,
            "fields": fields,
        })
    if not measures:
        raise ValueError("no measures found")
    return measures
