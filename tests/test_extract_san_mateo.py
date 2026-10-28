"""The San Mateo measures extractor on a tiny copy of the election page and the resolution readings."""

import pytest

from pipeline.extract import san_mateo_measures as ex

PDF = "https://smcacre.gov/system/files/2026-07/52-ENG-M{n}-Contest%20Code-Reso-X_Redacted.pdf"


def link(n, label):
    doc = f"https%3A%2F%2Fsmcacre.gov%2Fsystem%2Ffiles%2F2026-07%2F52-ENG-M{n}-Contest%2520Code-Reso-X_Redacted.pdf"
    return f'<a href="/archival-document?document={doc}&amp;title=T" class="document-link"><svg></svg>{label}</a><br>'


def panel(heading, threshold, n):
    return (f'<smc-accordion><smc-accordion-panel slot="panels"><h5 slot="heading">{heading}</h5>'
            f'<div class="wysiwyg"><p>{threshold}</p><p>{link(n, "Resolution and Full Text")}'
            f'{link(n + "IA", "Impartial Analysis")}</p></div></smc-accordion-panel></smc-accordion>')


PAGE = ("<h3>Statewide Measures</h3><p>See the state guide.</p>"
        "<h3>County Measures</h3>" + panel("Measure L – San Mateo County Charter Amendment Measure – Extreme Weather "
                                           "Events", "Majority Voter Approval Required", "1")
        + "<h3>Regional Measure</h3>" + panel("Regional Transit Measure – Public Transit Revenue Measure District: "
                                              "Transactions and Use Tax Measure", "Majority Voter Approval Required", "2")
        + "<h3>School District Measures</h3>" + panel("Measure R – Burlingame School District: Bond Measure",
                                                      "55% Voter Approval Required", "3")
        + "<h3>City Measures</h3>" + panel("Measure N – Town of Portola Valley: Town Charter and Property Transfer "
                                           "Tax Measure", "Majority Voter Approval Required", "4")
        + "<h3>Voter Education and Outreach Toolkit</h3>")

TEXTS = {
    "1": "a) The form of the ballot question is as follows:\nCOUNTY CHARTER AMENDMENT\nShall the San Mateo County "
         "Charter be amended to add a provision to the Charter Preamble designating long-term\nresilience as a "
         "County priority?\nYES NO\nSECTION 6.\nShall the San Mateo County Charter be amended to add a provision "
         "to the\nCharter Preamble designating long-term resilience as a County priority?",
    "2": "To prevent major service cuts to BART and other transit, shall the measure be adopted?",
    "3": "To repair aging Burlingame schools and maintain academic excellence, shall the measure be adopted?",
    "4": "Town of Portola Valley Autonomy Measure. Shall the measure maintaining Portola Valley's\n"
         "independent status be adopted?",
}


def field(text, url, label):
    return {"text": text, "source_url": url}


def pages(texts=TEXTS):
    out = {ex.URL: {"body": PAGE.encode("utf-8")}}
    for n, text in texts.items():
        out[PDF.format(n=n)] = {"text": text}
    return out


@pytest.fixture
def few_measures(monkeypatch):
    keep = {k: ex.QUESTIONS[k] for k in ("L", "RTM", "R", "N")}
    monkeypatch.setattr(ex, "QUESTIONS", keep)


def test_measures_with_questions_cut_from_the_resolutions(few_measures):
    got = {m["number"]: m for m in ex.extract(pages(), field)}
    assert list(got) == ["L", "RTM", "R", "N"]
    assert got["L"]["id"] == "local-sm-l"
    assert got["L"]["jurisdiction"] == {"level": "local", "county": "San Mateo", "name": "San Mateo County"}
    assert got["L"]["title"]["text"] == "Charter Amendment Measure – Extreme Weather Events"
    # stated twice in the resolution, with different line breaks: one question
    assert got["L"]["fields"]["ballot_question"]["text"] == (
        "Shall the San Mateo County Charter be amended to add a provision to the Charter Preamble designating "
        "long-term resilience as a County priority?")
    assert got["RTM"]["jurisdiction"]["name"] == "Public Transit Revenue Measure District"
    assert got["R"]["fields"]["measure_type"]["text"] == "55% Voter Approval Required"
    assert got["R"]["fields"]["district"]["text"] == "Burlingame School District"
    assert got["N"]["jurisdiction"]["name"] == "Town of Portola Valley"
    assert got["N"]["fields"]["ballot_question"]["text"].startswith("Town of Portola Valley Autonomy Measure. Shall")
    assert got["N"]["fields"]["ballot_question"]["source_url"] == PDF.format(n="4")
    assert got["N"]["documents"] == [
        {"label": "Measure N: Resolution and Full Text (PDF)", "url": PDF.format(n="4")},
        {"label": "Measure N: Impartial Analysis (PDF)", "url": PDF.format(n="4IA")}]


def test_statements_that_differ_are_refused(few_measures):
    texts = dict(TEXTS, **{"1": TEXTS["1"].replace("County priority?\nYES", "priority of the County?\nYES")})
    with pytest.raises(ValueError, match="Measure L"):
        ex.extract(pages(texts), field)


def test_missing_question_or_pdf_is_refused(few_measures):
    with pytest.raises(ValueError, match="Measure R"):
        ex.extract(pages(dict(TEXTS, **{"3": "No question on this page."})), field)
    with pytest.raises(ValueError, match="raw store"):
        ex.extract(pages({k: v for k, v in TEXTS.items() if k != "2"}), field)


def test_a_measure_dropped_from_the_page_is_refused(monkeypatch):
    monkeypatch.setattr(ex, "QUESTIONS", {k: ex.QUESTIONS[k] for k in ("L", "RTM", "R", "N", "EE")})
    with pytest.raises(ValueError, match="EE"):
        ex.extract(pages(), field)


def test_unexpected_headings_are_refused():
    with pytest.raises(ValueError):
        ex.parse_heading("City Measures", "Measure Q – City of Atlantis: Tax Measure")
    with pytest.raises(ValueError):
        ex.parse_heading("Regional Measure", "Regional Transit Measure – Some Other District: Tax")
    with pytest.raises(ValueError):
        ex.panels(PAGE.replace("55% Voter Approval Required", "Approval Required"))
