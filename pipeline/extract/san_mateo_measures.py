"""Extractor: San Mateo County Registrar of Voters (ACRE), local measures for November 3, 2026.

The election page lists every measure under "County Measures", "Regional Measure", "School District
Measures" and "City Measures" as a panel: a heading ("Measure R – Burlingame School District: Bond
Measure"), the vote needed ("55% Voter Approval Required") and links to the official PDFs. Each link
goes through /archival-document?document=<PDF URL>; the PDF URL is taken from that parameter.

The ballot question is not on the page. It is cut from the measure's "Resolution and Full Text" PDF,
where the governing body set the question (the four county charter amendments share one PDF). Most of
those PDFs are scans, read by OCR (pdf_ocr in the source file); a few have a usable text layer. The
resolutions say the question appears on the ballot "substantially" in this form, so the printed ballot
may differ slightly. QUESTIONS gives, per measure, the words the question starts with; the question runs
from there to the first "?". If a resolution states the question more than once, every statement must
read the same. Anything unexpected raises ValueError.
"""

import re
from urllib.parse import parse_qs, unquote, urlparse

from thinkballot.sourcetext import html_to_text

URL = "https://smcacre.gov/elections/november-3-2026-statewide-general-election"
LABEL = "San Mateo County Registrar of Voters: November 3, 2026 Statewide General Election"
PDF_LABEL = "San Mateo County Registrar of Voters: Measure {letter}, Resolution and Full Text (PDF)"
COUNTY = "San Mateo"
CODE = "sm"
TRANSIT_DISTRICT = "Public Transit Revenue Measure District"
SECTIONS = ["County Measures", "Regional Measure", "School District Measures", "City Measures"]
CITIES = {"Belmont", "Brisbane", "Burlingame", "East Palo Alto", "Half Moon Bay", "Menlo Park", "Pacifica",
          "Portola Valley", "Redwood City", "San Bruno", "San Carlos", "San Mateo"}
THRESHOLD_RE = re.compile(r"^(Majority|55%|2/3) Voter Approval Required$")
HEADING_RE = re.compile(r"^(?:Measure (?P<letter>[A-Z]{1,2})|(?P<rtm>Regional Transit Measure)) – (?P<rest>.+)$")

CHARTER = "Shall the San Mateo County Charter be amended to "
QUESTIONS = {  # letter: the words the ballot question starts with, in its resolution PDF
    "L": CHARTER + "add a provision to the Charter Preamble designating",
    "AA": CHARTER + "add a provision to the Charter Preamble affirming",
    "J": CHARTER + "extend the period",
    "U": CHARTER + "require that supervisorial districts",
    "RTM": "To prevent major service cuts",
    "R": "To repair aging Burlingame schools",
    "Z": "With funds that cannot be taken",
    "M": "With funds that cannot be taken",
    "T": "To renew expiring local funding",
    "K": "To protect outstanding educational programs",
    "V": "Without increasing current tax rates",
    "W": "To improve elementary and middle school",
    "Y": "Shall the ordinance providing funding",
    "X": "Shall the measure updating the City's Business License",
    "D": "To support city services",
    "O": "East Palo Alto Community/Water/Public Safety",
    "CC": "Shall the measure providing that no person",
    "I": "Shall the Measure, amending",
    "Q": "Shall Ordinance No. 2026-01",
    "P": "Should the measure, which prohibits",
    "BB": "Pacifica City Services Measure.",
    "N": "Town of Portola Valley Autonomy Measure.",
    "E": "Shall the measure repealing Redwood City",
    "S": "Shall City of San Bruno Ordinance",
    "DD": "Shall the City of San Bruno Safe and Sane",
    "EE": "San Bruno Essential Services Protection Measure.",
    "G": "To provide funding for San Carlos",
    "H": "To provide funding for San Mateo",
    "F": "Shall the measure amending the City of San Mateo",
}


def _text(fragment):
    return " ".join(html_to_text(fragment).split())


def pdf_url(href):
    """The official PDF behind an /archival-document?document=<url> link (or a direct link)."""
    href = href.replace("&amp;", "&")
    if href.startswith("/archival-document"):
        docs = parse_qs(urlparse(href).query).get("document")
        if not docs or len(docs) != 1:
            raise ValueError(f"archival link without one document: {href}")
        href = docs[0]
    if not href.startswith("https://smcacre.gov/system/files/") or not href.endswith(".pdf"):
        raise ValueError(f"unexpected document link: {href}")
    return href.replace(" ", "%20")  # the PDF as the crawler fetched it (spaces encoded)


def panels(raw):
    """[(section, heading, threshold, [(link label, pdf url)])] in page order."""
    out = []
    parts = re.split(r'<h3>([^<]+)</h3>', raw)
    for section, chunk in zip(parts[1::2], parts[2::2]):
        section = _text(section)
        if section not in SECTIONS:
            continue
        found = re.findall(r'<h5 slot="heading">(.*?)</h5>(.*?)</smc-accordion-panel>', chunk, re.S)
        if not found:
            raise ValueError(f"section {section!r} has no measures")
        for heading, body in found:
            paras = [_text(p) for p in re.findall(r"<p>(.*?)</p>", body, re.S)]
            threshold = paras[0] if paras else ""
            if not THRESHOLD_RE.match(threshold):
                raise ValueError(f"{_text(heading)}: unexpected vote threshold {threshold!r}")
            links = [(_text(label), pdf_url(href)) for href, label in
                     re.findall(r'<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.S)]
            out.append((section, _text(heading), threshold, links))
    if [s for s in SECTIONS if s not in {p[0] for p in out}]:
        raise ValueError("not every measure section was found on the page")
    return out


def parse_heading(section, heading):
    """(letter, jurisdiction name, district as printed, title)."""
    m = HEADING_RE.match(heading)
    if not m:
        raise ValueError(f"unexpected measure heading: {heading!r}")
    rest = m.group("rest")
    if section == "County Measures":
        district, sep, title = rest.partition(" Charter Amendment Measure – ")
        if district != "San Mateo County" or not sep or not m.group("letter"):
            raise ValueError(f"unexpected county measure heading: {heading!r}")
        return m.group("letter"), "San Mateo County", district, "Charter Amendment Measure – " + title
    district, sep, title = rest.partition(": ")
    if not sep or not title:
        raise ValueError(f"unexpected measure heading: {heading!r}")
    if section == "Regional Measure":
        if not m.group("rtm") or district != TRANSIT_DISTRICT:
            raise ValueError(f"unexpected regional measure heading: {heading!r}")
        return "RTM", TRANSIT_DISTRICT, district, title
    if m.group("rtm"):
        raise ValueError(f"unexpected measure heading: {heading!r}")
    if section == "School District Measures":
        if not district.endswith("District"):
            raise ValueError(f"unexpected school district: {district!r}")
        return m.group("letter"), district, district, title
    city = re.fullmatch(r"(?:City|Town) of (.+)", district)
    if not city or city.group(1) not in CITIES:
        raise ValueError(f"unexpected city: {district!r}")
    return m.group("letter"), district, district, title


def question(text, start, letter):
    """The ballot question: from `start` to the first "?" after it; every statement of it must read alike."""
    flat = " ".join(text.split())
    found = {flat[i:flat.index("?", i) + 1] for i in (m.start() for m in re.finditer(re.escape(start), flat))
             if "?" in flat[i:]}
    if len(found) != 1:
        raise ValueError(f"Measure {letter}: expected one ballot question starting {start!r}, found {len(found)}")
    q = found.pop()
    if len(q.split()) < 8 or len(q) > 1500:
        raise ValueError(f"Measure {letter}: unexpected ballot question {q[:80]!r}")
    return q


def extract(pages, field):
    if URL not in pages:
        raise ValueError(f"missing from the raw store: {URL}")
    measures, seen = [], set()
    for section, heading, threshold, links in panels(pages[URL]["body"].decode("utf-8")):
        letter, name, district, title = parse_heading(section, heading)
        if letter in seen:
            raise ValueError(f"Measure {letter} is listed twice")
        seen.add(letter)
        resolution = [url for label, url in links if label.startswith("Resolution")]
        if len(resolution) != 1:
            raise ValueError(f"Measure {letter}: expected one Resolution link, found {len(resolution)}")
        url = resolution[0]
        if url not in pages or "text" not in pages[url]:
            raise ValueError(f"Measure {letter}: resolution PDF missing from the raw store: {url}")
        if letter not in QUESTIONS:
            raise ValueError(f"Measure {letter}: no ballot question start known for this measure")
        label = PDF_LABEL.format(letter=letter)
        measures.append({
            "id": f"local-{CODE}-{letter.lower()}", "number": letter,
            "title": field(title, URL, LABEL),
            "jurisdiction": {"level": "local", "county": COUNTY, "name": name},
            "topics": [], "notes": [], "arguments_url": None,
            "documents": [{"label": f"Measure {letter}: {text} (PDF)", "url": link} for text, link in links],
            "fields": {
                "measure_type": field(threshold, URL, LABEL),
                "district": field(district, URL, LABEL),
                "ballot_question": field(question(pages[url]["text"], QUESTIONS[letter], letter), url, label),
            },
        })
    missing = set(QUESTIONS) - seen
    if missing:
        raise ValueError(f"measures no longer on the page: {sorted(missing)}")
    return measures
