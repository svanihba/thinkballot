"""After the polls close: counting-the-votes text instead of how-to-vote, results first on the home page."""

import datetime as dt
import re

import pytest
import requests

from thinkballot import config
from thinkballot.services.web import app as web_app
from tests.test_results import ELECTION, TITLES, sample_results

UTC = dt.timezone.utc
BEFORE = dt.datetime(2026, 11, 4, 3, 59, tzinfo=UTC)  # 7:59 p.m. PT on election day
AFTER = dt.datetime(2026, 11, 4, 4, 0, tzinfo=UTC)  # 8:00 p.m. PT: the polls close


@pytest.mark.parametrize("now, closed", [(BEFORE, False), (AFTER, True)])
def test_polls_close_at_8pm_pacific_on_election_day(now, closed):
    assert web_app.polls_closed({"date": ELECTION}, now) is closed


def test_no_election_date_means_polls_not_closed():
    assert web_app.polls_closed(None, AFTER) is False
    assert web_app.polls_closed({"name": "x"}, AFTER) is False


@pytest.mark.parametrize("path", ["/", "/ballot"])
def test_how_to_vote_until_the_polls_close(server, monkeypatch, path):
    monkeypatch.setattr(web_app, "utcnow", lambda: BEFORE)
    html = requests.get(server + path).text
    assert "How to vote by November 3" in html
    assert "After election day" not in html


@pytest.mark.parametrize("path", ["/", "/ballot", "/es/", "/zh/ballot"])
def test_counting_the_votes_after_the_polls_close(server, monkeypatch, path):
    monkeypatch.setattr(web_app, "utcnow", lambda: AFTER)
    html = requests.get(server + path).text
    assert 'id="howto-h"' in html
    assert "How to vote by November 3" not in html
    assert "Not registered yet?" not in html and "Find a voting location" not in html
    assert "https://california.ballottrax.net/voter/" in html  # track your ballot still helps
    assert "https://electionresults.sos.ca.gov/" in html
    if path in ("/", "/ballot"):
        assert "After election day" in html
        assert "postmarked on or before November 3 can be counted if they arrive by November 10" in html
        assert "unofficial until the Secretary of State certifies the results, by December 11" in html


def test_after_certification_the_block_says_so(server, monkeypatch):
    monkeypatch.setattr(web_app, "utcnow", lambda: AFTER + dt.timedelta(days=40))
    monkeypatch.setattr(config, "RESULTS_CERTIFIED", True)
    html = requests.get(server + "/").text
    assert "The Secretary of State has certified the results." in html
    assert "unofficial until" not in html and "arrive by November 10" not in html


def test_zip_note_is_accurate_everywhere(server):
    for path in ["/", "/es/", "/zh/", "/neutral", "/es/neutral", "/zh/neutral"]:
        html = requests.get(server + path).text
        assert "never stored" not in html and "then discard it" not in html, path
    assert ("Unless your browser sends Global Privacy Control or Do Not Track, it is kept for 60 days for site "
            "statistics, never linked to an account.") in requests.get(server + "/").text


def test_counting_text_is_translated(server, monkeypatch):
    monkeypatch.setattr(web_app, "utcnow", lambda: AFTER)
    es = requests.get(server + "/es/").text
    assert "Después del día de las elecciones" in es and "a más tardar el 10 de noviembre" in es
    zh = requests.get(server + "/zh/").text
    assert "最晚於11月10日寄達" in zh and "最晚於12月11日" in zh
    assert "之前寄達" not in zh


def render_landing(results, now=AFTER):
    from flask import render_template
    app = web_app.create_app()
    election = {"name": "November 3, 2026 California General Election", "date": ELECTION}
    measures = [{"id": f"prop-{n}", "number": n, "title": TITLES[n], "summary": "S", "measure_type": None}
                for n in ("39", "45")]
    with app.test_request_context("/"):
        return render_template("landing.html", election=election, count=len(measures), sample_zip="94087",
                               measures=measures, results=results, after_polls=web_app.polls_closed(election, now))


def test_home_page_leads_with_results_when_there_are_some():
    html = render_landing(sample_results())
    assert 'class="home-results"' in html, "results section missing"
    assert html.index('class="home-results"') < html.index('class="pillars"')
    s = html[html.index('class="home-results"'):html.index('class="pillars"')]
    assert s.count('class="results results-compact"') == 2
    assert 'href="/prop/prop-39"' in s and 'href="/prop/prop-45"' in s
    assert s.index("prop-39") < s.index("prop-45")  # official order
    assert "Unofficial results" in s
    for loaded in ["win", "lead", "pass", "fail", "landslide", "ahead", "behind"]:
        assert not re.search(rf"\b{loaded}", re.sub(r"<[^>]+>", " ", s), re.I), loaded


def test_home_page_has_no_results_section_without_results():
    assert 'class="home-results"' not in render_landing(None)
    assert 'class="home-results"' not in render_landing({"available": False})


def test_certified_heading_on_home_page():
    html = render_landing(sample_results(status="certified"))
    s = re.search(r'<section class="home-results".*', html, re.S).group(0)
    assert "Certified results" in s and "Unofficial" not in s[: s.index("</h2>")]


@pytest.mark.parametrize("status, flag", [("certified", False), ("unofficial", True)])
def test_one_source_decides_certified(monkeypatch, status, flag):
    # The results service's status wins when there are results, so the page never contradicts itself.
    monkeypatch.setattr(config, "RESULTS_CERTIFIED", flag)
    html = render_landing(sample_results(status=status))
    if status == "certified":
        assert "The Secretary of State has certified the results." in html and "unofficial until" not in html
    else:
        assert "unofficial until the Secretary of State certifies" in html and "has certified" not in html


def test_measure_missing_from_the_feed_says_so():
    res = sample_results()
    del res["measures"]["45"]
    s = render_landing(res).split('class="home-results"')[1]
    item = s[s.index("prop-45"):]
    assert "No results reported yet." in item[:item.index("</li>")]


def test_home_status_line_says_how_complete_the_count_is():
    res = sample_results()
    s = render_landing(res).split('home-results-status"')[1].split("</p>")[0]
    assert res["reporting"]["text"] in s


def test_compact_results_are_not_repeated_landmarks():
    html = render_landing(sample_results())
    assert '<section class="results results-compact"' not in html
    assert html.count('class="results results-compact"') == 2
