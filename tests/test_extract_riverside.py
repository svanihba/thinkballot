"""Riverside County local-measure extractor, on tiny inline copies of the official layouts."""

import pytest

from pipeline.extract import riverside_measures as rv

SUMMARY = """\
Measure B - Beaumont USD Adopt Bonds to Repair/Upgrade School Facilities
to Support College/Career Readiness (Vote for 1)
Candidate Party Total
BONDS YES 0 N/A
Measure I - Hemet USD Adopt Bonds to Repair/Upgrade Schools Facilities to
Support College/Career Readiness and Improve School... (Vote for 1)
Measure Q - City of Hemet Public Safety, Essential City Services Measure (Vote
for 1)
Measure U - City of Banning Amending the Land Uses for Property to Allow
General Commercial, Industrial, Open Space - Parks a... (Vote for 1)
"""


def test_summary_report_gives_jurisdiction_and_title():
    got = rv.contests(SUMMARY)
    assert got["B"] == ("Beaumont USD", "Beaumont Unified School District",
                        "Adopt Bonds to Repair/Upgrade School Facilities to Support College/Career Readiness")
    assert got["Q"] == ("City of Hemet", "City of Hemet", "Public Safety, Essential City Services Measure")
    # names the report cut off with "..." end at their last whole phrase
    assert got["I"][2] == "Adopt Bonds to Repair/Upgrade Schools Facilities to Support College/Career Readiness"
    assert got["U"][2] == "Amending the Land Uses for Property to Allow General Commercial, Industrial"


def test_summary_report_refuses_an_unknown_jurisdiction():
    with pytest.raises(ValueError):
        rv.contests("Measure Z - City of Nowhere Sales Tax Measure (Vote for 1)")
    with pytest.raises(ValueError):
        rv.contests(SUMMARY + SUMMARY)


def test_every_measure_is_either_sourced_or_pending():
    assert not set(rv.QUESTIONS) & set(rv.PENDING)
    assert set(rv.QUESTIONS) | set(rv.PENDING) == set("ABCEHIMPQRSTUVWY") | {"AA"}
    for url, kind, start in rv.QUESTIONS.values():
        assert url.startswith("https://") and kind in rv.KIND_LABELS and len(start.split()) >= 3


def test_extract_skips_pending_measures_and_refuses_unlisted_ones(monkeypatch):
    monkeypatch.setattr(rv, "QUESTIONS", {})
    monkeypatch.setattr(rv, "PENDING", {"C": "waiting for a capture"})
    pages = {rv.SUMMARY: {"text": "Measure C - City of Perris General Business License Tax (Vote for 1)"}}
    assert rv.extract(pages, lambda *a: a) == []
    assert rv.SKIPPED[0]["letter"] == "C"
    pages[rv.SUMMARY]["text"] += "\nMeasure ZZ - City of Perris Another Tax Measure (Vote for 1)"
    with pytest.raises(ValueError):
        rv.extract(pages, lambda *a: a)
