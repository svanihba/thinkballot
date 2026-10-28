"""The San Diego County measures extractor, on a tiny copy of the sample-ballot pamphlet layout."""

import pytest

from pipeline.extract import san_diego_measures as ex

BALLOT = """\
OFFICIAL BALLOT
GUBERNATORIAL GENERAL ELECTION
NOVEMBER 3, 2026
MEASURE A A TRANSPARENT,
ACCOUNTABLE, MODERN COUNTY
GOVERNMENT Shall the San Diego
County Charter be amended to clarify
non-interference provisions; and update
terminology and structure of the County Charter?
YES NO
MEASURE G Grossmont-Cuyamaca
District Bond With funds that cannot be taken, shall the
District's measure to improve/expand • •
classrooms remove asbestos/mold • •
be adopted, authorizing $624 million of bonds?
BONDS - YES BONDS - NO
"""

SECTIONS = """\
SD 600-048
SAN DIEGO COUNTY
MEASURE A
`
PR-Q00001-1-ENG
(This Measure will appear on the ballot in the following form.)
MEASURE A
A TRANSPARENT, ACCOUNTABLE, MODERN COUNTY GOVERNMENT
Shall the San Diego County Charter be amended to clarify non-interference provisions; and
updateterminology and structure of the County Charter?
This measure requires Simple Majority (50%+1) of those voting on the measure.
COUNTY COUNSEL IMPARTIAL ANALYSIS
SD 600-074
GROSSMONT-CUYAMACA COMMUNITY COLLEGE DISTRICT
MEASURE G
PR-S00002-1-ENG
(This measure will appear on the ballot in the following form.)
MEASURE G
Grossmont-Cuyamaca District Bond With funds that cannot be taken, shall the District's measure to
• improve/expand classrooms
• remove asbestos/mold
be adopted, authorizing $624 million of bonds?
Bonds—Yes Bonds—No
This measure requires 55% of those voting on the measure.
"""


def test_question_keeps_spaces_title_and_bullets():
    got = ex.pamphlet_measures(BALLOT + SECTIONS)
    a, g = got["A"], got["G"]
    assert a["title"] == "A TRANSPARENT, ACCOUNTABLE, MODERN COUNTY GOVERNMENT"
    # the section lost a space ("updateterminology"); the ballot page's reading is used
    assert a["question"].endswith("and update terminology and structure of the County Charter?")
    assert a["vote"] == "Simple Majority (50%+1)" and a["jurisdiction"] == "SAN DIEGO COUNTY"
    # the ballot page scrambles the bullets; the section's order is used, the bonds line is dropped
    assert g["title"] is None and g["vote"] == "55%"
    assert g["question"].endswith("measure to • improve/expand classrooms • remove asbestos/mold be adopted, "
                                  "authorizing $624 million of bonds?")


def test_section_and_ballot_page_must_agree():
    with pytest.raises(ValueError, match="differ"):
        ex.pamphlet_measures(BALLOT.replace("$624 million", "$625 million") + SECTIONS)


def test_every_expected_measure_is_required():
    pages = {"https://www.sdvote.com/content/dam/rov/en/sb/SB-ENG-600.pdf": {"text": BALLOT + SECTIONS}}
    with pytest.raises(ValueError, match="measures missing"):
        ex.extract(pages, lambda text, url, label: {"text": text, "source_url": url})


def test_display_names():
    assert ex.display_name("CITY OF SOLANA BEACH") == "City of Solana Beach"
    assert ex.display_name("LA MESA-SPRING VALLEY SCHOOL DISTRICT") == "La Mesa-Spring Valley School District"
