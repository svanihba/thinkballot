"""The real proposition data: every field sits in the right slot and links to the right page.

(The seed script separately proves every field appears word for word on its official page.)
"""

import json

import pytest

from thinkballot import config

DATA = json.loads((config.ROOT / "data" / "measures.json").read_text())


def test_fourteen_propositions_for_3_nov_2026():
    assert DATA["election"]["date"] == "2026-11-03"
    assert [m["number"] for m in DATA["measures"]] == ["1", "2", "3", "4", "5", "37", "38", "39", "40", "41",
                                                      "42", "43", "44", "45"]


@pytest.mark.parametrize("m", DATA["measures"], ids=lambda m: m["id"])
def test_fields_are_in_the_right_slots(m):
    f, n = m["fields"], m["number"]
    assert f["yes_means"]["text"].startswith("A YES vote on this measure means")
    assert f["no_means"]["text"].startswith("A NO vote on this measure means")
    assert "Fiscal Impact" not in f["summary"]["text"]
    assert "Supporters" not in f["fiscal_effect"]["text"]
    assert "Opponents" not in f["supporters"]["text"]
    for name in ("summary", "yes_means", "no_means", "fiscal_effect", "argument_for", "argument_against",
                 "supporters", "opponents"):
        assert f[name]["source_url"] == f"https://voterguide.sos.ca.gov/propositions/{n}/", name
        assert f[name]["text"].strip(), name
    assert f["analysis"]["source_url"] == f"https://voterguide.sos.ca.gov/propositions/{n}/analysis.htm"
    assert len(f["analysis"]["text"].split()) > 150
