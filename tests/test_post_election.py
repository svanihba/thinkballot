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
    assert "Counting the votes" not in html


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
        assert "Counting the votes" in html
        assert "postmarked on or before November 3 are counted if they arrive by November 10" in html
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
    assert "It is kept for 60 days for site statistics, never linked to an account." in requests.get(server + "/").text


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
