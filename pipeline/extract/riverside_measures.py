"""Extractor: Riverside County Registrar of Voters, local measures for November 3, 2026.

The list of measures comes from the Registrar's Election Summary Report (published before election day,
with zero counts): every contest "Measure X - <jurisdiction> <title> (Vote for 1)". The Registrar's web
pages refuse automated clients, so each ballot question is cut from the best official text that can be
fetched and read: the county voter information guide's sample ballot (one PDF per ballot type), the
Registrar's notice of election, or the city's / district's own notice, measure page or resolution
(read by OCR where the resolution is a scan). Each measure's notes say which kind of document it was.

Measures whose official question is not in the raw store yet are listed in PENDING: they are skipped and
logged (SKIPPED), never guessed. Anything else unexpected raises ValueError.
"""

import re

from thinkballot.sourcetext import html_to_text

from .san_bernardino_measures import cut_question

SUMMARY = "https://voteinfo.net/sites/g/files/aldnop371/files/2026-10/ElectionSummaryReportRPT%20%285%29.pdf"
SUMMARY_LABEL = "Riverside County Registrar of Voters: Election Summary Report, November 3, 2026 General Election"
VOTEINFO = "https://voteinfo.net/sites/g/files/aldnop371/files/2026-08/"
COUNTY = "Riverside"
CODE = "rv"

SAMPLE_BALLOT = "sample_ballot"
ROV_NOTICE = "rov_notice"
SB_ROV_NOTICE = "sb_rov_notice"
CITY_PAGE = "city_page"
RESOLUTION = "resolution"

KIND_LABELS = {
    SAMPLE_BALLOT: "county voter information guide (sample ballot)",
    ROV_NOTICE: "Registrar of Voters notice of election",
    SB_ROV_NOTICE: "San Bernardino County Registrar of Voters notice of the measure",
    CITY_PAGE: "city's measure page",
    RESOLUTION: "resolution placing the measure on the ballot",
}

# letter -> (document, kind, first words of the question). The question runs from the first words to
# the first "?" after them, in the document's text (OCR text for a scanned PDF, see pdf_ocr).
QUESTIONS = {
    "A": ("https://docs.voteinfo.net/voterInformation/root1103/ballots/bt000001.pdf", SAMPLE_BALLOT,
          "Riverside County Traffic Relief, Pothole/Road Repair Investment Renewal Without raising tax rates"),
    "B": ("https://uploads.rov.sbcounty.gov/ROV/Elections/2026/1103/Measures/BeaumontUSD/RES_BUSD.pdf", RESOLUTION,
          "Without increasing current tax rates, to repair/replace"),
    "E": ("https://canyonlakeca.govoffice3.com/uploads/dm/11851/ResolutionNo.202640Calling2026ElectiononInitiative.pdf",
          RESOLUTION, "CANYON LAKE PUBLIC SAFETY AND EMERGENCY RESPONSE PROTECTION MEASURE;"),
    "I": (VOTEINFO + "Measure%20I%20-%20Hemet%20USD%20eng.pdf", ROV_NOTICE, "To repair and upgrade aging classrooms"),
    "M": (VOTEINFO + "Measure%20M-Murrieta%20Valley%20USD%20eng.pdf", ROV_NOTICE,
          "Without increasing current tax rates, to fix"),
    "P": (VOTEINFO + "Measure%20P%20-Desert%20Recreation%20Dist%20-Eng.pdf", ROV_NOTICE,
          "LOCAL PARK REPAIR/SAFETY AND SENIOR/YOUTH SERVICES MEASURE."),
    "Q": ("https://www.hemetca.gov/DocumentCenter/View/12619", RESOLUTION,
          "Hemet Public Safety, Essential City Services Measure."),
    "R": ("https://ranchomirageca.gov/residents/city_services/measure_r.php", CITY_PAGE,
          "RANCHO MIRAGE PUBLIC SAFETY, ROADS, CITY SERVICES MEASURE."),
    "S": (VOTEINFO + "Measure%20S-Temecula%20Valley%20USD%20-eng.pdf", ROV_NOTICE, "To provide safe, modern schools"),
    "T": ("https://www.lake-elsinore.org/DocumentCenter/View/5682", RESOLUTION,
          "Shall the office of City Treasurer be appointive?"),
    "AA": (VOTEINFO + "Measure%20AA-Perris%20Union%20High%20School%20District%20eng.pdf", ROV_NOTICE,
           "Without increasing current tax rates, to repair/"),
    "Y": ("https://uploads.rov.sbcounty.gov/ROV/Elections/2026/1103/Measures/SBCCD/Notice_SBCCD.pdf", SB_ROV_NOTICE,
          "Local College Affordability, Job Training"),
}

# Measures whose official ballot question is not in the raw store yet, and why.
PENDING = {
    "C": "City of Perris measure page refuses automated clients; waiting for a supervised browser capture.",
    "H": "City of Indian Wells measure page refuses automated clients; waiting for a supervised browser capture.",
    "U": "No City of Banning document with the ballot question found yet; the county guide for a Banning "
         "ballot type is needed.",
    "V": "No City of Banning document with the ballot question found yet; the county guide for a Banning "
         "ballot type is needed.",
    "W": "No City of Banning document with the ballot question found yet; the county guide for a Banning "
         "ballot type is needed.",
}
SKIPPED = []  # measures left out this run: {letter, jurisdiction, reason}

DISTRICTS = {  # how the summary report names each non-city jurisdiction, and the full name
    "San Bernardino CCD": "San Bernardino Community College District",
    "Beaumont USD": "Beaumont Unified School District",
    "Hemet USD": "Hemet Unified School District",
    "Murrieta Valley USD": "Murrieta Valley Unified School District",
    "Temecula Valley USD": "Temecula Valley Unified School District",
    "Perris Union HSD": "Perris Union High School District",
    "Riverside County": "Riverside County",
    "Desert Recreation District": "Desert Recreation District",
}
CITIES = ("City of Banning", "City of Canyon Lake", "City of Hemet", "City of Indian Wells", "City of Lake Elsinore",
          "City of Perris", "City of Rancho Mirage")
CONTEST_RE = re.compile(r"Measure ([A-Z]{1,2}) - (.+?) \(Vote for 1\)")


def contests(text):
    """{letter: (jurisdiction as printed, full name, title)} for every measure in the summary report."""
    flat = " ".join(text.split())
    found = {}
    for letter, rest in CONTEST_RE.findall(flat):
        printed = [j for j in CITIES + tuple(DISTRICTS) if rest.startswith(j + " ")]
        if len(printed) != 1:
            raise ValueError(f"summary report: unknown jurisdiction in {rest!r}")
        printed = printed[0]
        if letter in found:
            raise ValueError(f"summary report: measure {letter} listed twice")
        found[letter] = (printed, DISTRICTS.get(printed, printed), short_title(rest[len(printed) + 1:]))
    if not found:
        raise ValueError("summary report: no measures")
    return found


def short_title(name):
    """The contest name after the jurisdiction. The report cuts long names off with "..."; such a name
    is shortened to its last whole phrase (before the last " and", ", " or " to ")."""
    if name.endswith("..."):
        name = name[:-3].rstrip()
        cuts = [name.rfind(sep) for sep in (" and", ", ", " to ")]
        if max(cuts) <= 0:
            raise ValueError(f"summary report: cannot shorten {name!r}")
        name = name[:max(cuts)]
    if len(name.split()) < 2:
        raise ValueError(f"summary report: title too short: {name!r}")
    return name[0].upper() + name[1:]


def notes_for(kind, name):
    if kind == SAMPLE_BALLOT:
        return ["Ballot question as printed on the county's sample ballot."]
    if kind == ROV_NOTICE:
        return ["Ballot question from the Riverside County Registrar of Voters' notice of election."]
    if kind == SB_ROV_NOTICE:
        return ["Ballot question from the San Bernardino County Registrar of Voters' notice of the measure "
                "(the district is mostly in San Bernardino County)."]
    if kind == CITY_PAGE:
        return [f"Ballot question from the {name}'s official page about the measure; the printed ballot may "
                "differ slightly."]
    return [f"Ballot question from the {name}'s resolution placing the measure on the ballot; the printed "
            "ballot may differ slightly."]


def document_text(page):
    if "text" in page:
        return page["text"]
    return html_to_text(page["body"].decode("utf-8", "replace"))


def extract(pages, field):
    if SUMMARY not in pages or "text" not in pages[SUMMARY]:
        raise ValueError(f"missing from the raw store: {SUMMARY}")
    found = contests(pages[SUMMARY]["text"])
    if set(QUESTIONS) & set(PENDING) or set(found) != set(QUESTIONS) | set(PENDING):
        raise ValueError(f"summary report lists {sorted(found)}; questions known for {sorted(QUESTIONS)}, "
                         f"pending {sorted(PENDING)}")
    measures = []
    SKIPPED.clear()
    for letter in sorted(found, key=lambda x: (len(x), x)):
        printed, name, title = found[letter]
        if letter in PENDING:
            SKIPPED.append({"letter": letter, "jurisdiction": name, "reason": PENDING[letter]})
            print(f"riverside_measures: PENDING measure {letter} ({name}): {PENDING[letter]}")
            continue
        url, kind, start = QUESTIONS[letter]
        if url not in pages:
            raise ValueError(f"measure {letter}: {url} missing from the raw store")
        question = cut_question(document_text(pages[url]), start)
        label = f"{name}: {KIND_LABELS[kind]}, Measure {letter}"
        documents = [{"label": f"Measure {letter}: {KIND_LABELS[kind]}", "url": url},
                     {"label": "Riverside County Registrar of Voters: Election Summary Report (PDF)", "url": SUMMARY}]
        measures.append({
            "id": f"local-{CODE}-{letter.lower()}", "number": letter,
            "title": field(title, SUMMARY, SUMMARY_LABEL),
            "jurisdiction": {"level": "local", "county": COUNTY, "name": name},
            "topics": [], "notes": notes_for(kind, name), "arguments_url": None, "documents": documents,
            "fields": {
                "district": field(printed, SUMMARY, SUMMARY_LABEL),
                "ballot_question": field(question, url, label),
            },
        })
    return measures
