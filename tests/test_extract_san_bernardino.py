"""San Bernardino County local-measure extractor, on tiny inline copies of the official layouts."""

import pytest

from pipeline.extract import san_bernardino_measures as sb

ROW = """<tr>
<td style="text-align: center">{letter_cell}</td>
<td><a href="https://uploads.rov.sbcounty.gov/x/RES_X.pdf" target="_blank" rel="noopener">City of Needles</a></td>
<td><a href="https://uploads.rov.sbcounty.gov/x/FT_X.pdf" target="_blank" rel="noopener">Charter Amendment</a></td>
<td><a href="https://uploads.rov.sbcounty.gov/x/IA_X.pdf" target="_blank" rel="noopener">Impartial</a></td>
<td><ul><li>No Argument Against was filed.</li></ul></td>
<td style="text-align: center">50% + 1</td>
</tr>"""
HEADER = "<tr>\n<th><strong>Letter</strong></th>\n<th>Jurisdiction</th>\n</tr>"


def test_rows_read_letter_jurisdiction_description_threshold_and_documents():
    raw = HEADER + ROW.format(letter_cell="D") + ROW.format(
        letter_cell='<a href="https://uploads.rov.sbcounty.gov/x/Notice_X.pdf">K</a>')
    d, k = sb.measure_rows(raw)
    assert (d["letter"], d["jurisdiction"], d["description"], d["threshold"]) == (
        "D", "City of Needles", "Charter Amendment", "50% + 1")
    assert [x["label"] for x in d["documents"]] == [
        "Measure D: resolution (PDF)", "Measure D: full text (PDF)", "Measure D: Impartial (PDF)"]
    assert k["documents"][0] == {"label": "Measure K: notice of measure (PDF)",
                                 "url": "https://uploads.rov.sbcounty.gov/x/Notice_X.pdf"}


def test_rows_refuse_an_unexpected_table():
    with pytest.raises(ValueError):
        sb.measure_rows(ROW.format(letter_cell="D").replace("50% + 1", "see notice"))
    with pytest.raises(ValueError):
        sb.measure_rows(ROW.format(letter_cell="D") + ROW.format(letter_cell="D"))


# A resolution: the question is printed twice, once with the ballot's YES/NO boxes read into its lines.
RESOLUTION = """\
following measure:
“To maintain fire, paramedic, police, 911 response, anti-gang
programs; clean
YES
and maintain public areas; for NO
general City services; shall the measure be adopted?”
SECTION 4.
WHEREAS, there will be submitted to the voters the following measure:
“To maintain fire, paramedic, police, 911 response, anti-gang
programs; clean
and maintain public areas; for
general City services; shall the measure be adopted?”
Yes
No
"""


def test_question_is_cut_from_the_copy_without_ballot_boxes():
    assert sb.cut_question(RESOLUTION, "To maintain fire, paramedic, police") == (
        "To maintain fire, paramedic, police, 911 response, anti-gang programs; clean and maintain public "
        "areas; for general City services; shall the measure be adopted?")


def test_question_with_boxes_in_every_copy_is_refused():
    only_mixed = RESOLUTION.split("SECTION 4.")[0]
    with pytest.raises(ValueError):
        sb.cut_question(only_mixed, "To maintain fire, paramedic, police")


def test_upper_case_no_inside_a_question_is_kept():
    text = "To improve schools, with audits, NO\nmoney for salaries, only local facilities?\nBONDS YES\nBONDS NO\n"
    assert sb.cut_question(text, "To improve schools").endswith("NO money for salaries, only local facilities?")


def test_every_measure_on_the_page_needs_a_known_question_source():
    assert set(sb.QUESTIONS) == set("YZABCIDEFGHJKLMNOPQR")
    for url, kind, start, reading in sb.QUESTIONS.values():
        assert url.endswith(".pdf") and kind in sb.DOC_LABELS and reading in ("text", "crop_text")
