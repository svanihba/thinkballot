"""Extractor: San Bernardino County Registrar of Voters, local measures for November 3, 2026.

The Registrar's "2026 General Election - Local Measures" page has one table row per measure: letter,
jurisdiction, description, impartial analysis, arguments and the vote needed to pass, each linking the
official PDFs. The page does not print the ballot questions. Each question is cut from the best official
text that pdftotext reads cleanly (the county's sample ballot PDF uses a font without a text mapping, so
it cannot be read): the Registrar's "Notice of Measure to Be Voted On" where there is one, otherwise the
city's own notice of election or the resolution / ordinance that placed the measure on the ballot.

Where the YES/NO boxes printed beside a question get mixed into the PDF text, or a page footer splits it,
the question is read from a cropped region of the page (pdf_crop_reading in the source file). Each
measure's notes say which kind of document its question came from. Anything unexpected raises ValueError.
"""

import html
import re

from thinkballot.sourcetext import html_to_text

PAGE = "https://elections.sbcounty.gov/elections/2026/1103/measures/"
ROV = "https://uploads.rov.sbcounty.gov/ROV/Elections/2026/1103/Measures/"
PAGE_LABEL = "San Bernardino County Registrar of Voters: 2026 General Election, Local Measures"
COUNTY = "San Bernardino"
CODE = "sb"

ROV_NOTICE = "rov_notice"
CITY_NOTICE = "city_notice"
RESOLUTION = "resolution"
ORDINANCE = "ordinance"

# letter -> (document, kind, first words of the question, reading). The question runs from the first
# words to the first "?" after them; reading "crop_text" means the cropped region of the page.
QUESTIONS = {
    "Y": (ROV + "SBCCD/Notice_SBCCD.pdf", ROV_NOTICE, "Local College Affordability, Job Training", "text"),
    "Z": (ROV + "SBCityUSD/Notice_SBCUSD.pdf", ROV_NOTICE, "To repair/upgrade aging classrooms", "text"),
    "A": (ROV + "UplandUSD/Notice_UUSD.pdf", ROV_NOTICE, "To improve the quality of education", "text"),
    "B": (ROV + "BeaumontUSD/RES_BUSD.pdf", RESOLUTION, "Without increasing current tax rates", "text"),
    "C": (ROV + "BarstowCCD/Notice_BCCD.pdf", ROV_NOTICE, "Barstow Community College Repair", "text"),
    "I": (ROV + "County/Notice_SBCTA.pdf", ROV_NOTICE, "LOCAL TRANSPORTATION IMPROVEMENT PROGRAM", "text"),
    "D": (ROV + "CityofNeedles/29/RES_CityofNeedles.pdf", RESOLUTION,
          "Shall the proposed amendment to Section 503 of the City Charter to", "text"),
    "E": (ROV + "CityofHighland/RES_CityofHighland.pdf", RESOLUTION, "To maintain local funding for police", "text"),
    "F": (ROV + "CityofChino/RES_CityofChino.pdf", RESOLUTION, "Without taxing residents", "text"),
    "G": (ROV + "CityofTwentyninePalms/RES_TP.pdf", RESOLUTION, "Shall the measure funding services", "text"),
    "H": (ROV + "CityofOntario/RES_Ontario.pdf", RESOLUTION, "To maintain fire, paramedic, police", "text"),
    "J": (ROV + "CityofChinoHills/RES_ChinoHills.pdf", RESOLUTION, "Chino Hills Services Measure:", "text"),
    "K": ("https://cityofneedles.com/wp-content/uploads/2026/08/2026-27-TOT-Increase-SBEMP-WITH-683-AC.pdf",
          RESOLUTION, "Shall the measure to maintain and improve quality of life", "text"),
    "L": (ROV + "CityofNeedles/30/FT_CityofNeedles.pdf", ORDINANCE, "To improve the City of Needles", "crop_text"),
    "M": ("https://uplandca.gov/Documents/Government/City%20Manager/Measure%20M/Measure%20M%20Notice%20of%20Election.pdf",
          CITY_NOTICE, "Upland Business License Reform Measure", "text"),
    "N": (ROV + "CityofGrandTerrace/RES_GT.pdf", RESOLUTION, "GRAND TERRACE GENERAL SERVICES MEASURE.", "crop_text"),
    "O": (ROV + "CityofColton/RES_CityofColton.pdf", RESOLUTION, "Shall the office of Colton City Treasurer", "text"),
    "P": (ROV + "CityofAdelanto/RES_CityofAdelanto.pdf", RESOLUTION, "Shall the measure to provide funding for Adelanto",
          "crop_text"),
    "Q": (ROV + "SBMCHD/Notice_SBMCHD.pdf", ROV_NOTICE, "To repair and upgrade 75-year-old", "text"),
    "R": (ROV + "RimoftheWorldRPD/Notice_ROTW.pdf", ROV_NOTICE, "Shall Rim of the World Recreation", "text"),
}

DOC_LABELS = {ROV_NOTICE: "Registrar of Voters notice of the measure", CITY_NOTICE: "city notice of election",
              RESOLUTION: "resolution placing the measure on the ballot",
              ORDINANCE: "ordinance placing the measure on the ballot"}

ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
LINK_RE = re.compile(r"<a href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.S)
# A line that is only a ballot box word, or a line ending in YES / Yes / No (an upper-case "NO" can end a
# line of a question: "NO money for salaries").
BOX_RE = re.compile(r"^(?:BONDS )?(?:YES|NO|Yes|No)$|\s(?:YES|Yes|No)$")
QUOTES = "\"“”'"


def _clean(fragment):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def measure_rows(raw):
    """[{letter, jurisdiction, description, threshold, documents}] from the measures page table."""
    rows = []
    for row in ROW_RE.findall(raw):
        if "<th" in row:
            continue
        cells = CELL_RE.findall(row)
        if len(cells) != 6:
            raise ValueError(f"measures page: a row has {len(cells)} cells, expected 6: {_clean(row)[:80]!r}")
        letter, jurisdiction, description, threshold = (_clean(cells[i]) for i in (0, 1, 2, 5))
        if not re.fullmatch(r"[A-Z]{1,2}", letter):
            raise ValueError(f"measures page: {letter!r} is not a measure letter")
        if not (jurisdiction and description and re.fullmatch(r"\d+% \+ 1|\d+%|2/3", threshold)):
            raise ValueError(f"measures page: row {letter} is not jurisdiction / description / vote to pass")
        documents = []
        for href, text in LINK_RE.findall(row):
            if not href.endswith(".pdf") or href in [d["url"] for d in documents]:
                continue
            name = _clean(text)
            name = {letter: "notice of measure", jurisdiction: "resolution", description: "full text"}.get(name, name)
            documents.append({"label": f"Measure {letter}: {name} (PDF)", "url": href})
        rows.append({"letter": letter, "jurisdiction": jurisdiction, "description": description,
                     "threshold": threshold, "documents": documents})
    letters = [r["letter"] for r in rows]
    if not rows or len(set(letters)) != len(letters):
        raise ValueError(f"measures page: no measures, or a letter listed twice: {letters}")
    return rows


def cut_question(text, start):
    """The question that starts with `start`: up to the first "?", quotes trimmed. Every copy in the text
    is tried; copies with YES/NO box words mixed into their lines are refused. All clean copies must agree."""
    found = set()
    for m in re.finditer(r"\s+".join(map(re.escape, start.split())), text):
        end = text.find("?", m.start())
        if end < 0:
            continue
        lines = text[m.start():end + 1].split("\n")
        if any(BOX_RE.search(line) for line in lines):
            continue
        found.add(" ".join(" ".join(lines).split()))
    if len(found) != 1:
        raise ValueError(f"{len(found)} clean copies of the question starting {start!r}")
    question = found.pop()
    if len(question.split()) < 6:
        raise ValueError(f"question starting {start!r} is too short")
    return question


def notes_for(kind, jurisdiction):
    if kind == ROV_NOTICE:
        return ["Ballot question from the San Bernardino County Registrar of Voters' notice of the measure."]
    if kind == CITY_NOTICE:
        return [f"Ballot question from the {jurisdiction}'s notice of election."]
    return [f"Ballot question from the {jurisdiction}'s {kind} placing the measure on the ballot; "
            "the printed ballot may differ slightly."]


def extract(pages, field):
    if PAGE not in pages:
        raise ValueError(f"missing from the raw store: {PAGE}")
    rows = measure_rows(pages[PAGE]["body"].decode("utf-8"))
    if {r["letter"] for r in rows} != set(QUESTIONS):
        raise ValueError(f"measures page lists {sorted(r['letter'] for r in rows)}; questions are known for "
                         f"{sorted(QUESTIONS)}")
    page_text = html_to_text(pages[PAGE]["body"].decode("utf-8"))
    measures = []
    for row in rows:
        letter = row["letter"]
        for value in (row["jurisdiction"], row["description"], row["threshold"]):
            if value not in " ".join(page_text.split()):
                raise ValueError(f"measure {letter}: {value!r} is not in the page text")
        url, kind, start, reading = QUESTIONS[letter]
        if url not in pages or reading not in pages[url]:
            raise ValueError(f"measure {letter}: no {reading} for {url} in the raw store")
        question = cut_question(pages[url][reading], start)
        documents = list(row["documents"])
        if url not in [d["url"] for d in documents]:
            documents.insert(0, {"label": f"Measure {letter}: {DOC_LABELS[kind]} (PDF)", "url": url})
        q_label = f"{row['jurisdiction']}: {DOC_LABELS[kind]}, Measure {letter}"
        measures.append({
            "id": f"local-{CODE}-{letter.lower()}", "number": letter,
            "title": field(row["description"], PAGE, PAGE_LABEL),
            "jurisdiction": {"level": "local", "county": COUNTY, "name": row["jurisdiction"]},
            "topics": [], "notes": notes_for(kind, row["jurisdiction"]), "arguments_url": None,
            "documents": documents,
            "fields": {
                "measure_type": field(row["threshold"], PAGE, PAGE_LABEL),
                "district": field(row["jurisdiction"], PAGE, PAGE_LABEL),
                "ballot_question": field(question, url, q_label),
            },
        })
    return measures
