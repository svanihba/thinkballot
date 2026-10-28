"""Extractor: Alameda County Registrar of Voters, measures list for the November 3, 2026 election.

The ROV's measures page (https://www.alamedacountyca.gov/rov_app/measures) loads the list for the
chosen election from /rov_app/measures/election/<id>; election 260 is November 03, 2026. In that
fragment each group (<span id="pollingLocationDiv_...">) has an <h2> category ("DISTRICT", "SCHOOL",
"CITY OF ALAMEDA", ...), then one <div class="measureDescGroup"> per measure: an <h3> "Measure L - City
Of Alameda - GO Bond Measure", the vote needed ("Percentage Passing: 2/3") and the ballot question.
"""

import re

from thinkballot.sourcetext import html_to_text

URL = "https://www.alamedacountyca.gov/rov_app/measures/election/260"
LABEL = "Alameda County Registrar of Voters: Measures, November 03, 2026 General Election"
COUNTY = "Alameda"
TRANSIT_DISTRICT = "Public Transit Revenue Measure District"


def _text(fragment):
    return " ".join(html_to_text(fragment).split())


def _one(pattern, chunk, what):
    found = re.findall(pattern, chunk, re.S)
    if len(found) != 1:
        raise ValueError(f"expected one {what}, found {len(found)}")
    return found[0]


def _jurisdiction(category, district):
    """(jurisdiction name, district text from the heading or None) for a measure's group."""
    if category == "DISTRICT":
        if district is not None:
            raise ValueError(f"unexpected district measure heading: {district}")
        return TRANSIT_DISTRICT, None
    if category == "SCHOOL":
        if not district.endswith(" USD"):
            raise ValueError(f"unexpected school district: {district}")
        return district[:-len(" USD")] + " Unified School District", district
    if category.startswith("CITY OF "):
        city = category[len("CITY OF "):].title()
        if district.lower() != f"city of {city.lower()}":
            raise ValueError(f"group {category} holds a measure for {district}")
        return f"City of {city}", district
    raise ValueError(f"unexpected measure group: {category}")


def extract(pages, field):
    if URL not in pages:
        raise ValueError(f"missing from the raw store: {URL}")
    raw = pages[URL]["body"].decode("utf-8")
    if "measureDescGroup" not in raw:
        raise ValueError("no measures on the page")
    groups = re.split(r'<span id="pollingLocationDiv_', raw)[1:]
    if not groups:
        raise ValueError("no measure groups found")
    measures, seen = [], set()
    for group in groups:
        category = _text(_one(r'<div class="polling-list-table-header[^"]*">(.*?)</div>', group, "group heading"))
        items = re.split(r'<div class="measureDescGroup">', group)[1:]
        if not items:
            raise ValueError(f"group {category} has no measures")
        for item in items:
            heading = _text(_one(r'<h3 class="measureDesc">(.*?)</h3>', item, "measure heading"))
            parts = [p.strip() for p in heading.split(" - ")]
            if not re.fullmatch(r"Measure [A-Z]{1,3}", parts[0]) or len(parts) < 2:
                raise ValueError(f"unexpected measure heading: {heading}")
            letter = parts[0].split(" ", 1)[1]
            district = parts[1] if len(parts) > 2 else None
            title = " - ".join(parts[2:]) if len(parts) > 2 else parts[1]
            name, district = _jurisdiction(category, district)
            threshold = _text(_one(r'<div class="measurePerc">(.*?)</div>', item, "vote threshold"))
            if not threshold.startswith("Percentage Passing: "):
                raise ValueError(f"unexpected vote threshold: {threshold}")
            question = _text(_one(r'<p class="measureText">(.*?)</p>', item, "ballot question"))
            if "?" not in question:
                raise ValueError(f"Measure {letter}: ballot question has no question mark")
            mid = f"local-al-{letter.lower()}"
            if mid in seen:
                raise ValueError(f"Measure {letter} appears twice")
            seen.add(mid)
            fields = {
                "measure_type": field(threshold, URL, LABEL),
                "ballot_question": field(question, URL, LABEL),
            }
            if district:
                fields["district"] = field(district, URL, LABEL)
            measures.append({
                "id": mid, "number": letter,
                "title": field(title, URL, LABEL),
                "jurisdiction": {"level": "local", "county": COUNTY, "name": name},
                "topics": [], "documents": [], "notes": [], "arguments_url": None,
                "fields": fields,
            })
    if not measures:
        raise ValueError("no measures found")
    return measures
