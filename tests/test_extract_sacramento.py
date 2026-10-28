"""The Sacramento County measures extractor on a tiny copy of the "Current Measure Information" page."""

import pytest

from pipeline.extract import sacramento_measures as ex


def item(heading, *paras):
    body = "".join(f"<p>{p}</p>" for p in paras)
    return (f'<div class="accordion-item border-bottom"><h3 class="accordion-header">'
            f'<button class="accordion-button collapsed" type="button">\n\t{heading}\n </button></h3>'
            f'<div class="accordion-collapse collapse"><div class="accordion-body">{body}</div></div></div>')


PAGE = ("<p>November 3, 2026, General Election</p>"
        + item("Measure D: Natomas Unified School District", "55% Vote Required",
               "<b>Schools Measure.</b> Shall the measure be adopted?", "Impartial Analysis<br />Prepared by County Counsel")
        + item("WITHDRAWN -- Measure F: City of Sacramento", "Shall the measure be adopted?")
        + item("Measure L: City of Galt", "Shall the offices be appointive?&nbsp;", "Impartial Analysis<br />Prepared by City Counsel"))


def field(text, url, label):
    return {"text": text, "source_url": url}


def run(page):
    return ex.extract({ex.URL: {"body": page.encode("utf-8")}}, field)


def test_extracts_measures_and_skips_withdrawn():
    d, l = run(PAGE)
    assert d["id"] == "local-sa-d" and d["title"]["text"] == "Natomas Unified School District"
    assert d["fields"]["measure_type"]["text"] == "55% Vote Required"
    assert d["fields"]["ballot_question"]["text"] == "Schools Measure. Shall the measure be adopted?"
    assert l["jurisdiction"] == {"level": "local", "county": "Sacramento", "name": "City of Galt"}
    assert "measure_type" not in l["fields"]
    assert l["fields"]["ballot_question"]["text"] == "Shall the offices be appointive?"


def test_unexpected_layout_raises():
    with pytest.raises(ValueError):
        run(PAGE.replace("Measure L: City of Galt", "Item L - City of Galt"))
    with pytest.raises(ValueError):
        run(PAGE.replace("Impartial Analysis<br />Prepared by City Counsel", "Full Text"))
    with pytest.raises(ValueError):
        run(PAGE.replace("November 3, 2026", "June 2, 2026"))
