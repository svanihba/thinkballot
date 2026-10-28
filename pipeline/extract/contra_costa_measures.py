"""Extractor: Contra Costa County Clerk-Recorder-Elections, one page per local measure (November 3, 2026).

Each measure has its own page (m9001-en-2 ... m9013-en) whose main text reads, in order:
the measure letter ("Measure M" / "MEASURE M"), the jurisdiction in capitals ("CITY OF CLAYTON"), an
optional title in capitals ("CITY OF CLAYTON SALES TAX MEASURE."), the ballot question, then the
impartial analysis. Regional Transit Measure RTM has a title line but no jurisdiction line; its district
is printed in the heading of the impartial analysis ("PUBLIC TRANSIT REVENUE MEASURE DISTRICT'S ...").
The election data feed (getQuestion JSON) is not parsed: the HTML pages are the source.
"""

import html
import re

from thinkballot.sourcetext import html_to_text

LABEL = "Contra Costa County Clerk-Recorder-Elections: measure page"
COUNTY = "Contra Costa"
ELECTION_HEADING = "November 3, 2026, General Election"
ANALYSIS = "IMPARTIAL ANALYSIS OF"
RTM_DISTRICT = "PUBLIC TRANSIT REVENUE MEASURE DISTRICT"

# letter -> (jurisdiction as printed on the page, jurisdiction name in normal case).
# RTM's printed jurisdiction is in the analysis heading instead (see RTM_DISTRICT).
MEASURES = {
    "RTM": (RTM_DISTRICT, "Public Transit Revenue Measure District"),
    "M": ("CITY OF CLAYTON", "City of Clayton"),
    "N": ("CITY OF CLAYTON", "City of Clayton"),
    "O": ("CITY OF CONCORD", "City of Concord"),
    "P": ("CITY OF HERCULES", "City of Hercules"),
    "Q": ("CITY OF RICHMOND", "City of Richmond"),
    "R": ("CITY OF SAN PABLO", "City of San Pablo"),
    "S": ("CITY OF SAN PABLO", "City of San Pablo"),
    "T": ("CITY OF WALNUT CREEK", "City of Walnut Creek"),
    "U": ("CITY OF WALNUT CREEK", "City of Walnut Creek"),
    "V": ("WEST CONTRA COSTA UNIFIED SCHOOL DISTRICT", "West Contra Costa Unified School District"),
    "W": ("ACALANES UNION HIGH SCHOOL DISTRICT", "Acalanes Union High School District"),
    "X": ("LIBERTY UNION HIGH SCHOOL DISTRICT", "Liberty Union High School District"),
}


def _lines(body):
    return html_to_text(body.decode("utf-8")).split("\n")


def _is_caps(line):
    return line == line.upper() and any(ch.isalpha() for ch in line)


def _documents(raw, url):
    """Links to official documents (impartial analysis, arguments) in the main content: https links on
    a .gov host between the impartial analysis heading and the footer. Navigation links are excluded."""
    start = raw.find(ANALYSIS)
    if start < 0:
        return []
    end = raw.find("<footer", start)
    section = raw[start:] if end < 0 else raw[start:end]
    docs = []
    for href, label in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', section, re.S):
        href = html.unescape(href)
        host = re.match(r"https://([^/]+)/", href)
        if not host or not host.group(1).endswith(".gov"):
            continue
        name = " ".join(html_to_text(label).split())
        if name:
            docs.append({"label": name, "url": href})
    return docs


def _parse(url, body):
    raw = body.decode("utf-8")
    text = html_to_text(raw)
    lines = text.split("\n")
    head = None
    for i in range(len(lines) - 1):
        m = re.fullmatch(r"Measure ([A-Z]+)", lines[i].strip(), re.I)
        if m and lines[i + 1].strip() == f"MEASURE {m.group(1)}":
            head = i + 2
            letter = m.group(1)
            break
    if head is None:
        raise ValueError(f"{url}: no 'Measure X' heading found")
    if letter not in MEASURES:
        raise ValueError(f"{url}: unexpected measure letter {letter}")
    printed, name = MEASURES[letter]
    end = next((j for j in range(head, len(lines)) if ANALYSIS in lines[j]), None)
    if end is None:
        raise ValueError(f"Measure {letter}: no impartial analysis heading after the question")
    block = lines[head:end]
    header = []
    for line in block:
        if not _is_caps(line):
            break
        header.append(line)
    question_lines = block[len(header):]
    if not question_lines:
        raise ValueError(f"Measure {letter}: no ballot question")
    question = "\n".join(question_lines)
    if "?" not in question:
        raise ValueError(f"Measure {letter}: the ballot question has no '?': {question[:80]!r}")
    if letter == "RTM":
        if header != ["REGIONAL TRANSIT MEASURE"]:
            raise ValueError(f"Measure RTM: unexpected title lines {header}")
        title = header[0]
        analysis_heading = lines[end]
        if not analysis_heading.startswith(RTM_DISTRICT + "’S LEGAL COUNSEL"):
            raise ValueError(f"Measure RTM: unexpected analysis heading {analysis_heading!r}")
        district = printed
    else:
        if header[:1] != [printed] or len(header) not in (1, 2):
            raise ValueError(f"Measure {letter}: expected jurisdiction {printed!r} then at most one title, "
                             f"got {header}")
        district = printed
        title = header[-1]
    return {"letter": letter, "name": name, "district": district, "title": title, "question": question,
            "text": text, "raw": raw}


def extract(pages, field):
    html_pages = {url: row for url, row in pages.items() if "text/html" in (row["content_type"] or "")}
    if len(html_pages) != 13:
        raise ValueError(f"expected 13 HTML measure pages, found {len(html_pages)}")
    measures, seen = [], set()
    for url in sorted(html_pages):
        page = html_pages[url]
        parsed = _parse(url, page["body"])
        letter = parsed["letter"]
        if letter in seen:
            raise ValueError(f"Measure {letter} appears on two pages")
        seen.add(letter)
        text = parsed["text"]
        for value in (parsed["district"], parsed["title"], parsed["question"]):
            if value not in text:
                raise ValueError(f"Measure {letter}: text not found word for word on the page: {value[:60]!r}")
        measures.append({
            "id": f"local-cc-{letter.lower()}", "number": letter,
            "title": field(parsed["title"], url, LABEL),
            "jurisdiction": {"level": "local", "county": COUNTY, "name": parsed["name"]},
            "topics": [], "documents": _documents(parsed["raw"], url), "notes": [], "arguments_url": None,
            "fields": {
                "district": field(parsed["district"], url, LABEL),
                "ballot_question": field(parsed["question"], url, LABEL),
            },
        })
    if seen != set(MEASURES):
        raise ValueError(f"measure letters {sorted(seen)} are not the expected {sorted(MEASURES)}")
    return sorted(measures, key=lambda m: m["id"])
