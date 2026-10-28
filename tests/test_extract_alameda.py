"""The Alameda County measures extractor on a tiny copy of the ROV's measures fragment."""

import pytest

from pipeline.extract import alameda_measures as ex

PAGE = """
<span id="pollingLocationDiv_DISTRICT">
  <h2 id="location-DISTRICT"><div class="polling-list-table-header ucase measureCategory">DISTRICT</div></h2>
  <div class="measureDescGroup">
    <h3 class="measureDesc">Measure RTM - Regional Transit Measure</h3>
    <div class="measurePerc">Percentage Passing:&nbsp;Majority</div>
    <p class="measureText">To keep transit running, shall the measure be adopted?</p>
  </div>
</span>
<span id="pollingLocationDiv_SCHOOL">
  <h2 id="location-SCHOOL"><div class="polling-list-table-header ucase measureCategory">SCHOOL</div></h2>
  <div class="measureDescGroup">
    <h3 class="measureDesc">Measure K - Sunol Glen USD - GO Bond Measure</h3>
    <div class="measurePerc">Percentage Passing:&nbsp;55%</div>
    <p class="measureText">Shall Sunol Glen Unified School District's measure be adopted?</p>
  </div>
</span>
<span id="pollingLocationDiv_CITY OF UNION CITY">
  <h2 id="location-CITY_OF_UNION_CITY"><div class="polling-list-table-header ucase measureCategory">CITY OF UNION CITY</div></h2>
  <div class="measureDescGroup">
    <h3 class="measureDesc">Measure II - City Of Union City - Essential Services Measure</h3>
    <div class="measurePerc">Percentage Passing:&nbsp;50% + 1</div>
    <p class="measureText"><b>Services.</b> Shall the measure
be adopted?</p>
  </div>
</span>
"""


def field(text, url, label):
    return {"text": text, "source_url": url}


def run(page):
    return ex.extract({ex.URL: {"body": page.encode("utf-8")}}, field)


def test_extracts_measures():
    rtm, k, ii = run(PAGE)
    assert rtm["id"] == "local-al-rtm" and rtm["jurisdiction"]["name"] == ex.TRANSIT_DISTRICT
    assert "district" not in rtm["fields"]
    assert k["jurisdiction"]["name"] == "Sunol Glen Unified School District"
    assert k["fields"]["district"]["text"] == "Sunol Glen USD"
    assert k["fields"]["measure_type"]["text"] == "Percentage Passing: 55%"
    assert k["title"]["text"] == "GO Bond Measure"
    assert ii["id"] == "local-al-ii" and ii["jurisdiction"] == {"level": "local", "county": "Alameda",
                                                                "name": "City of Union City"}
    assert ii["fields"]["ballot_question"]["text"] == "Services. Shall the measure be adopted?"


def test_unexpected_layout_raises():
    with pytest.raises(ValueError):
        run(PAGE.replace("CITY OF UNION CITY</div>", "WATER</div>"))
    with pytest.raises(ValueError):
        run(PAGE.replace("Measure K - ", "Item K - "))
    with pytest.raises(ValueError):
        run("<p>No measures</p>")
