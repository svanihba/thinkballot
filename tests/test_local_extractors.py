"""County local-measure extractors, on tiny inline copies of the official layouts (not the full PDFs)."""

import pytest

from pipeline.extract import los_angeles_measures as la

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
MEASURE RR: Shall the City Charter be amended to prohibit evictions based on nonpayment of rent in Santa Monica? Supporters: Someone Opponents: None
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
    # cut from the verified PDF text, which joined the line-end hyphen
    assert got[1]["question"] == ("MEASURE RR: Shall the City Charter be amended to prohibit evictions based on "
                                  "nonpayment of rent in Santa Monica?")
    assert got[2]["question"].endswith("tax rates, be adopted?")


def test_los_angeles_refuses_a_missing_measure():
    with pytest.raises(ValueError):
        la.parse(LA_LAYOUT.replace("LOCAL JURISDICTION MEASURES – (2)\n", "LOCAL JURISDICTION MEASURES – (3)\n"),
                 LA_TEXT)
