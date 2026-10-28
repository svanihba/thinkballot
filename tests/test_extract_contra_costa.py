"""The Contra Costa measures extractor on tiny inline copies of the per-measure pages."""

import pytest

from pipeline.extract import contra_costa_measures as ex


def page(letter, jurisdiction, question, title=None, analysis_heading=None):
    """A page shaped like the captured ones: nav text, the 'Measure X' heading, jurisdiction, optional
    title, the question, then the impartial analysis heading with one document link."""
    lines = ["<p>Accessibility</p>", f"<p>Measure {letter}</p>", f"<h2>MEASURE {letter}</h2>"]
    if jurisdiction:
        lines.append(f"<p>{jurisdiction}</p>")
    if title:
        lines.append(f"<p>{title}</p>")
    lines.append(f"<p>{question}</p>")
    lines.append("<hr />")
    lines.append(f"<p><strong>{analysis_heading or 'CITY ATTORNEY’S IMPARTIAL ANALYSIS OF'}<br />MEASURE {letter}</strong></p>")
    lines.append("<p>The analysis text.</p>")
    lines.append('<p><a href="https://www.contracostavote.gov/wp-content/uploads/M-analysis.pdf">Impartial Analysis</a></p>')
    lines.append('<footer><a href="https://www.contracosta.ca.gov/">ContraCosta.ca.gov</a></footer>')
    return "".join(lines).encode("utf-8")


def field(text, url, label):
    return {"text": text, "source_url": url}


def pages_for(bodies):
    return {f"https://www.contracostavote.gov/m{i}/": {"content_type": "text/html; charset=utf-8", "body": body}
            for i, body in enumerate(bodies)}


def city_page():
    return page("M", "CITY OF CLAYTON", "To provide local funding, shall the City of Clayton levy a 1% sales tax?",
                title="CITY OF CLAYTON SALES TAX MEASURE.")


def test_city_measure_with_title_line():
    url = "https://www.contracostavote.gov/m1/"
    m = ex._parse(url, city_page())
    assert m["letter"] == "M" and m["name"] == "City of Clayton"
    assert m["title"] == "CITY OF CLAYTON SALES TAX MEASURE."
    assert m["district"] == "CITY OF CLAYTON"


def test_measure_without_title_line_uses_jurisdiction_as_title():
    body = page("O", "CITY OF CONCORD", "Shall the measure be adopted to repair potholes?")
    m = ex._parse("u", body)
    assert m["title"] == "CITY OF CONCORD" and m["question"] == "Shall the measure be adopted to repair potholes?"


def test_multi_line_question_is_kept_line_by_line():
    body = page("W", "ACALANES UNION HIGH SCHOOL DISTRICT",
                "Shall the measure supporting schools by:<br />• Attracting teachers<br />• Maintaining class sizes be adopted?")
    m = ex._parse("u", body)
    assert m["question"] == "Shall the measure supporting schools by:\n• Attracting teachers\n• Maintaining class sizes be adopted?"


def test_rtm_district_comes_from_analysis_heading():
    body = page("RTM", None, "To prevent service cuts, shall the measure enacting a 0.5% tax be adopted?",
                title="REGIONAL TRANSIT MEASURE",
                analysis_heading="PUBLIC TRANSIT REVENUE MEASURE DISTRICT’S LEGAL COUNSEL IMPARTIAL ANALYSIS OF")
    m = ex._parse("u", body)
    assert m["district"] == "PUBLIC TRANSIT REVENUE MEASURE DISTRICT"
    assert m["name"] == "Public Transit Revenue Measure District"


def test_extract_builds_thirteen_measures_with_documents():
    bodies = []
    for letter, (printed, _name) in ex.MEASURES.items():
        if letter == "RTM":
            bodies.append(page("RTM", None, "Shall the measure be adopted?", title="REGIONAL TRANSIT MEASURE",
                               analysis_heading="PUBLIC TRANSIT REVENUE MEASURE DISTRICT’S LEGAL COUNSEL IMPARTIAL ANALYSIS OF"))
        else:
            bodies.append(page(letter, printed, f"Shall the {letter} measure be adopted?"))
    measures = ex.extract(pages_for(bodies), field)
    assert len(measures) == 13
    rtm = next(m for m in measures if m["number"] == "RTM")
    assert rtm["id"] == "local-cc-rtm"
    assert rtm["documents"] == [{"label": "Impartial Analysis",
                                 "url": "https://www.contracostavote.gov/wp-content/uploads/M-analysis.pdf"}]
    assert all("contracosta.ca.gov" not in d["url"] for m in measures for d in m["documents"])
    assert all(m["fields"]["ballot_question"]["text"].endswith("?") for m in measures)


def test_wrong_jurisdiction_raises():
    body = page("M", "CITY OF PITTSBURG", "Shall the measure be adopted?", title="CITY OF PITTSBURG MEASURE.")
    with pytest.raises(ValueError, match="expected jurisdiction"):
        ex._parse("u", body)


def test_question_without_question_mark_raises():
    body = page("M", "CITY OF CLAYTON", "The city shall levy a tax.", title="CITY OF CLAYTON SALES TAX MEASURE.")
    with pytest.raises(ValueError, match=r"no '\?'"):
        ex._parse("u", body)


def test_wrong_number_of_pages_raises():
    with pytest.raises(ValueError, match="expected 13"):
        ex.extract(pages_for([city_page()]), field)
