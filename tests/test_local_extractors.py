"""County local-measure extractors, on tiny inline copies of the official layouts (not the full PDFs)."""

import pytest

from pipeline.extract import los_angeles_measures as la
from pipeline.extract import orange_measures as oc

LA_LAYOUT = """\
COUNTY MEASURES – (1)
     LOS ANGELES COUNTY – (1)
     VOTE PASSAGE – Majority Vote 50%+
 A    PROPOSED COUNTY CHARTER AMENDMENT. Shall the measure amending the Los Angeles County
      Charter be adopted? Supporters: Someone Opponents: None submitted.

LOCAL JURISDICTION MEASURES – (2)
        CITY OF SANTA MONICA – (2)
        VOTE PASSAGE – Majority Vote 50%+1
RR    MEASURE RR: Shall the City Charter be amended to prohibit evictions based on non-
      payment of rent in Santa Monica? Supporters: Someone Opponents: None
      submitted.
                                                                                         16 | P a g e
LOCAL JURISDICTION MEASURES – (2) Continued
        CITY OF SANTA MONICA Continued– (2)
        VOTE PASSAGE – Majority Vote 50%+1
TT    MEASURE TT: Shall the measure, which maintains the existing transient occupancy tax
      rates, be adopted? Supporters: Someone Opponents: None submitted.
"""

LA_TEXT = """\
COUNTY MEASURES – (1)
A
LOS ANGELES COUNTY – (1)
VOTE PASSAGE – Majority Vote 50%+
PROPOSED COUNTY CHARTER AMENDMENT. Shall the measure amending the Los Angeles County
Charter be adopted? Supporters: Someone Opponents: None submitted.
LOCAL JURISDICTION MEASURES – (2)
RR
CITY OF SANTA MONICA – (2)
VOTE PASSAGE – Majority Vote 50%+1
RR MEASURE RR: Shall the City Charter be amended to prohibit evictions based on non-payment of rent in Santa Monica? Supporters: Someone Opponents: None
submitted.
16 | P a g e
TT
CITY OF SANTA MONICA Continued– (2)
VOTE PASSAGE – Majority Vote 50%+1
MEASURE TT: Shall the measure, which maintains the existing transient occupancy tax
rates, be adopted? Supporters: Someone Opponents: None submitted.
"""


def test_los_angeles_letters_line_up_with_their_questions():
    got = la.parse(LA_LAYOUT, LA_TEXT)
    assert [(m["letter"], m["name"], m["threshold"]) for m in got] == [
        ("A", "Los Angeles County", "Majority Vote 50%+"),
        ("RR", "City of Santa Monica", "Majority Vote 50%+1"),
        ("TT", "City of Santa Monica", "Majority Vote 50%+1")]
    # cut from the verified PDF text; the layout text split "non-" / "payment" across lines
    assert got[1]["question"] == ("MEASURE RR: Shall the City Charter be amended to prohibit evictions based on "
                                  "non-payment of rent in Santa Monica?")
    assert got[2]["question"].endswith("tax rates, be adopted?")


def test_los_angeles_refuses_a_missing_measure():
    with pytest.raises(ValueError):
        la.parse(LA_LAYOUT.replace("LOCAL JURISDICTION MEASURES – (2)\n", "LOCAL JURISDICTION MEASURES – (3)\n"),
                 LA_TEXT)


OC_SECTION = """\
Ballot Measures-H 11
Section
H City of Newport Beach, City of Newport Beach General
Plan - Amendment
Shall the measure to amend the City of Newport Beach's General Plan Land Use Element allowing new housing
units, be adopted?
What your vote means
YES
"""


def test_orange_section_splits_title_from_question():
    letter, jurisdiction, title, question = oc.parse_section(
        OC_SECTION, "City of Newport Beach, City of Newport Beach General Plan – Amendment")
    assert (letter, jurisdiction, title) == ("H", "City of Newport Beach", "City of Newport Beach General Plan - Amendment")
    assert question.startswith("Shall the measure") and question.endswith("be adopted?")


def test_orange_refuses_a_section_for_another_measure():
    with pytest.raises(ValueError):
        oc.parse_section(OC_SECTION, "City of Orange, Proposed Charter for the City of Orange")


def test_orange_refuses_a_question_whose_spaces_were_lost():
    squashed = OC_SECTION.replace("General Plan Land Use Element", "GeneralPlanLandUseElementallowingnewhousing")
    with pytest.raises(ValueError):
        oc.parse_section(squashed, "City of Newport Beach, City of Newport Beach General Plan – Amendment")
