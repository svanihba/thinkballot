"""The San Francisco measures extractor on a tiny copy of the measures page, the ballot questions letter and the RTM resolution."""

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

RTM_OCR = ("District Resolution No. 2\n"
           "the question to be provided to the Boards of Supervisors of the Counties of Alameda.\n"
           "To prevent major service cuts to BART and other transit, avoid increased traffic, and reduce\n"
           "pollution by: Preserving BART, Caltrain, VTA, SamTrans, AC Transit, Muni.\n"
           "generating approximately $980,000,000 annually, be adopted?\n\nand be it further")


def field(text, url, label):
    return {"text": text, "source_url": url}


def run(page=PAGE, letter=LETTER, ocr=RTM_OCR):
    pages = {ex.PAGE_URL: {"body": page.encode("utf-8")}, ex.PDF_URL: {"text": letter},
             ex.RTM_PDF_URL: {"text": ocr}}
    return ex.extract(pages, field)


def test_matches_questions_to_letters_by_title():
    a, b, _ = run()
    assert a["id"] == "local-sf-a" and a["title"]["text"] == "Contributions to the Housing Fund"
    assert a["fields"]["ballot_question"]["text"] == "Shall the City amend the Charter to change the Housing Trust Fund?"
    assert a["fields"]["ballot_question"]["source_url"] == ex.PDF_URL
    assert b["fields"]["ballot_question"]["text"] == "Shall the City amend the Charter to change the ballot measure process?"
    assert b["jurisdiction"] == {"level": "local", "county": "San Francisco", "name": "City and County of San Francisco"}


def test_rtm_question_is_cut_from_its_ocr_text():
    rtm = run()[-1]
    assert rtm["id"] == "local-sf-rtm" and rtm["number"] == "RTM"
    assert rtm["title"]["text"] == "Regional Transit Measure"
    assert rtm["jurisdiction"] == {"level": "local", "county": "San Francisco",
                                   "name": "Public Transit Revenue Measure District"}
    assert rtm["documents"] == [{"label": "Regional Transit Measure resolution (PDF)", "url": ex.RTM_PDF_URL}]
    q = rtm["fields"]["ballot_question"]
    assert q["text"].startswith("To prevent major service cuts to BART") and q["text"].endswith("be adopted?")
    assert "and be it further" not in q["text"] and q["source_url"] == ex.RTM_PDF_URL


def test_unclear_or_missing_matches_raise():
    with pytest.raises(ValueError):  # a question whose title matches no page title
        run(letter=LETTER.replace("Contributions to the Housing Trust Fund", "Parcel Tax for Parks"))
    with pytest.raises(ValueError):  # more lettered measures than questions
        run(page=PAGE + accordion("C - Parcel Tax"))
    with pytest.raises(ValueError):
        run(letter=LETTER.replace("Proposition entitled", "Measure"))


def test_rtm_question_missing_raises():
    with pytest.raises(ValueError):  # the resolution does not carry the regional question
        run(ocr="No question here, only a resolution. Shall it pass?")
    with pytest.raises(ValueError):  # no RTM entry on the page
        run(page=PAGE.replace("RTM - Regional Transit Measure", "Z - Something Else"))
