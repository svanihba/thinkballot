"""The San Francisco measures extractor on a tiny copy of the measures page and the ballot questions letter."""

import pytest

from pipeline.extract import san_francisco_measures as ex


def accordion(title):
    return f'<summary><h3 class="font-body" data-testid="accordion-title">{title}</h3></summary>'


PAGE = (accordion("Local Measures") + accordion("A - Contributions to the Housing Fund")
        + accordion("B - Changes to Ballot Measure Process") + accordion("RTM - Regional Transit Measure"))

LETTER = """Re: November 3, 2026 Ballot Questions
Dear Director Arntz:
Please find below the ballot questions for the November 3, 2026 election.
Proposition entitled “Changes to Ballot Measure Process”: “Shall the City amend the
Charter to change the ballot measure process?”
CITY AND COUNTY OF SAN FRANCISCO OFFICE OF THE CITY ATTORNEY
Letter to John Arntz
August 7, 2026
Proposition entitled “Contributions to the Housing Trust Fund”: “Shall the City amend
the Charter to change the Housing Trust Fund?”
Very truly yours,"""


def field(text, url, label):
    return {"text": text, "source_url": url}


def run(page=PAGE, letter=LETTER):
    return ex.extract({ex.PAGE_URL: {"body": page.encode("utf-8")}, ex.PDF_URL: {"text": letter}}, field)


def test_matches_questions_to_letters_by_title():
    a, b = run()
    assert a["id"] == "local-sf-a" and a["title"]["text"] == "Contributions to the Housing Fund"
    assert a["fields"]["ballot_question"]["text"] == "Shall the City amend the Charter to change the Housing Trust Fund?"
    assert a["fields"]["ballot_question"]["source_url"] == ex.PDF_URL
    assert b["fields"]["ballot_question"]["text"] == "Shall the City amend the Charter to change the ballot measure process?"
    assert b["jurisdiction"] == {"level": "local", "county": "San Francisco", "name": "City and County of San Francisco"}


def test_unclear_or_missing_matches_raise():
    with pytest.raises(ValueError):  # a question whose title matches no page title
        run(letter=LETTER.replace("Contributions to the Housing Trust Fund", "Parcel Tax for Parks"))
    with pytest.raises(ValueError):  # more lettered measures than questions
        run(page=PAGE + accordion("C - Parcel Tax"))
    with pytest.raises(ValueError):
        run(letter=LETTER.replace("Proposition entitled", "Measure"))
