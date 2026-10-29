"""Official results: strict parsing, fetch-if-stale, last good copy, and neutral YES/NO markup."""

import datetime as dt
import json
import re

import pytest
import requests

from thinkballot import config
from thinkballot.services.results import app as results_app
from thinkballot.services.results import feed
from thinkballot.services.results.app import http_fetch  # the real one (conftest takes the test server offline)

FIXTURES = config.ROOT / "tests" / "fixtures"
# Recorded verbatim from https://api.sos.ca.gov/returns/ballot-measures on 2026-10-27 (SoS test numbers).
RECORDED = (FIXTURES / "sos_ballot_measures_recorded_2026-10-27.json").read_text()
ELECTION = "2026-11-03"
TITLES = {m["number"]: m["title"]["text"] for m in json.loads((config.ROOT / "data" / "measures.json").read_text())
          ["measures"] if m["id"].startswith("prop-")}
UTC = dt.timezone.utc
NIGHT = dt.datetime(2026, 11, 4, 5, 0, tzinfo=UTC)  # 9 p.m. PT on election day


def election_night(time="November 3, 2026, 9:45 p.m.", **changes):
    """The recorded feed, in its exact format, as it would look after the polls close."""
    data = json.loads(RECORDED)
    data["ReportingTime"] = time
    data.update(changes)
    return data


def body(data):
    return json.dumps(data).encode()


# ---------- parsing ----------
def test_recorded_feed_is_rejected_before_the_polls_close():
    # On 2026-10-27 the SoS feed already listed this ballot's 14 propositions with test numbers.
    with pytest.raises(feed.FeedError, match="not after the 2026-11-03 polls closed"):
        feed.parse(RECORDED, ELECTION, TITLES)


def test_parse_election_night_feed():
    r = feed.parse(body(election_night()), ELECTION, TITLES)
    assert sorted(r["measures"], key=int) == sorted(TITLES, key=int)  # all 14, by proposition number
    p1 = r["measures"]["1"]
    assert (p1["yes_votes"], p1["no_votes"], p1["yes_percent"], p1["no_percent"]) == (211, 681, "23.7", "76.3")
    assert r["reporting"] == {"percent": 0.1, "precincts": 21, "precincts_total": 23863,
                              "text": "0.1% (21 of 23,863) precincts reporting"}
    assert r["as_of"] == "2026-11-03T21:45:00-08:00"


def test_parse_times():
    assert feed.parse_time("November 3, 2026, 12:05 a.m.").hour == 0
    assert feed.parse_time("November 3, 2026, 12:05 p.m.").hour == 12
    assert feed.parse_time("November 4, 2026, 1:30 AM").hour == 1
    for bad in ["Nov 3, 2026, 9:45 p.m.", "November 3, 2026", "November 31, 2026, 9:45 p.m.",
                "November 3, 2026, 13:45 p.m.", None, 5]:
        with pytest.raises(feed.FeedError):
            feed.parse_time(bad)


def mutate(fn):
    data = election_night()
    fn(data)
    return body(data)


@pytest.mark.parametrize("change", [
    lambda d: d.pop("ballot-measures"),
    lambda d: d.update(raceTitle="Ballot Measures - County Results"),
    lambda d: d.update(ReportingTime="soon"),
    lambda d: d.pop("ReportingTime"),
    lambda d: d.update(Reporting="lots of precincts reporting"),
    lambda d: d["ballot-measures"][0].update(yesVotes="2,11"),
    lambda d: d["ballot-measures"][0].update(yesVotes=211),          # a number, not the feed's string
    lambda d: d["ballot-measures"][0].update(yesVotes="-211"),
    lambda d: d["ballot-measures"][0].update(yesPercent="33.7"),     # does not match the counts
    lambda d: d["ballot-measures"][0].update(noPercent="176.3"),
    lambda d: d["ballot-measures"][0].pop("noVotes"),
    lambda d: d["ballot-measures"][0].update(Number="1A"),
    lambda d: d["ballot-measures"][1].update(Number="01"),           # listed twice
    lambda d: d["ballot-measures"][0].update(Name="Something Else Entirely. Initiative Statute."),
    lambda d: d["ballot-measures"].append(dict(d["ballot-measures"][0], Number="99")),
    lambda d: d["ballot-measures"].append("Prop 46"),
    lambda d: d.update({"ballot-measures": []}),
])
def test_unknown_format_is_rejected_whole(change):
    with pytest.raises(feed.FeedError):
        feed.parse(mutate(change), ELECTION, TITLES)


@pytest.mark.parametrize("raw", [b"", b"<html>Service Unavailable</html>", b"\xff\xfe", b"[]", b"x" * 600000])
def test_non_json_is_rejected(raw):
    with pytest.raises(feed.FeedError):
        feed.parse(raw, ELECTION, TITLES)


def test_other_elections_are_ignored():
    # A previous election, in the same format: its own date and propositions.
    prior = {"raceTitle": "Ballot Measures - Statewide Results", "Reporting": "100.0% (21,262 of 21,262) precincts "
             "reporting", "ReportingTime": "December 13, 2024, 3:12 p.m.", "ballot-measures": [
                 {"Name": "Authorizes Bonds for Public School and Community College Facilities. Legislative Statute.",
                  "Number": "02", "yesVotes": "8805916", "yesPercent": "58.6", "noVotes": "6223376",
                  "noPercent": "41.4"}]}
    with pytest.raises(feed.FeedError, match="polls closed"):
        feed.parse(body(prior), ELECTION, TITLES)
    # The same proposition numbers in a later election: the names don't match this ballot's titles.
    later = election_night(time="November 5, 2026, 9:00 a.m.")
    later["ballot-measures"] = [dict(later["ballot-measures"][0], Name="Authorizes Bonds For Water Projects.")]
    with pytest.raises(feed.FeedError, match="does not match"):
        feed.parse(body(later), ELECTION, TITLES)
    # Long after this election (past the results window): another election's feed.
    with pytest.raises(feed.FeedError, match="polls closed"):
        feed.parse(body(election_night(time="June 2, 2027, 9:00 p.m.")), ELECTION, TITLES)


def test_no_votes_yet_shows_nothing():
    data = election_night()
    for m in data["ballot-measures"]:
        m.update(yesVotes="0", noVotes="0", yesPercent="0.0", noPercent="0.0")
    with pytest.raises(feed.FeedError, match="no votes"):
        feed.parse(body(data), ELECTION, TITLES)
    data["ballot-measures"][0].update(yesVotes="3", noVotes="1", yesPercent="75.0", noPercent="25.0")
    assert list(feed.parse(body(data), ELECTION, TITLES)["measures"]) == ["1"]


def test_title_matching_ignores_case_and_punctuation():
    assert feed.name_matches("Limits Voters' Ability To Raise Revenues For Local Government Services. Legislative "
                             "Constitutional Amendment.", "Limit's Voters' Ability to Raise Revenues for Local "
                             "Government Services.")
    assert not feed.name_matches("Authorizes Bonds.", "Authorizes Bonds for Housing Affordability Programs.")


# ---------- fetch-if-stale and the last good copy ----------
class Stub:
    """Stands in for the network: returns the queued responses in order, counting calls."""

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    def __call__(self):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


TOKEN = {"X-TB-Internal": config.INTERNAL_TOKEN}


def make(tmp_path, fetch, now):
    clock = {"now": now}
    app = results_app.create_app(db_path=tmp_path / "results.sqlite3", fetch=fetch,
                                 catalog=lambda: (ELECTION, TITLES), clock=lambda: clock["now"])
    client = app.test_client()
    return (lambda: client.get("/results", headers=TOKEN).get_json()), clock


def test_nothing_is_fetched_or_shown_before_the_polls_close(tmp_path):
    stub = Stub(body(election_night()))
    get, _ = make(tmp_path, stub, dt.datetime(2026, 11, 4, 3, 59, tzinfo=UTC))  # 7:59 p.m. PT
    assert get() == {"available": False}
    assert stub.calls == 0


def test_fetches_at_most_every_five_minutes(tmp_path):
    first = election_night()
    second = election_night(time="November 3, 2026, 10:15 p.m.")
    second["ballot-measures"][0].update(yesVotes="311", yesPercent="31.3", noPercent="68.7")
    stub = Stub(body(first), body(second))
    get, clock = make(tmp_path, stub, NIGHT)
    r = get()
    assert r["available"] and r["status"] == "unofficial" and stub.calls == 1
    assert r["measures"]["1"]["yes_votes"] == 211 and r["as_of_text"] == "November 3, 2026, 9:45 p.m. PT"
    assert r["source_url"] == "https://api.sos.ca.gov/returns/ballot-measures"
    assert r["fetched_at"] == "2026-11-04T05:00:00+00:00"
    clock["now"] = NIGHT + dt.timedelta(minutes=4, seconds=59)
    assert get()["measures"]["1"]["yes_votes"] == 211 and stub.calls == 1  # still fresh: no request
    clock["now"] = NIGHT + dt.timedelta(minutes=5)
    r = get()
    assert stub.calls == 2 and r["measures"]["1"]["yes_votes"] == 311
    assert r["as_of_text"] == "November 3, 2026, 10:15 p.m. PT"


def test_failure_keeps_the_last_good_copy_with_its_time(tmp_path):
    stub = Stub(body(election_night()), results_app.FetchError("HTTP 503"), b"<html>maintenance</html>",
                mutate(lambda d: d["ballot-measures"][0].update(yesPercent="99.9")))
    get, clock = make(tmp_path, stub, NIGHT)
    good = get()
    for step in range(1, 4):
        clock["now"] = NIGHT + dt.timedelta(minutes=6 * step)
        r = get()
        assert r == good  # same numbers, same "as of" and fetched_at time: nothing new, nothing partial
    assert stub.calls == 4


def test_failure_before_any_good_copy_shows_nothing(tmp_path):
    get, _ = make(tmp_path, Stub(mutate(lambda d: d.update(raceTitle="Something new"))), NIGHT)
    assert get() == {"available": False}


def test_a_copy_for_another_election_is_not_served(tmp_path):
    get, _ = make(tmp_path, Stub(body(election_night())), NIGHT)
    assert get()["available"]
    app = results_app.create_app(db_path=tmp_path / "results.sqlite3", fetch=Stub(),
                                 catalog=lambda: ("2028-03-07", TITLES), clock=lambda: NIGHT)
    assert app.test_client().get("/results", headers=TOKEN).get_json() == {"available": False}


def test_certified_status(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RESULTS_CERTIFIED", True)
    get, _ = make(tmp_path, Stub(body(election_night())), NIGHT)
    assert get()["status"] == "certified"


def test_preview_uses_the_fixture_and_its_own_database(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RESULTS_FIXTURE", str(FIXTURES / "sos_ballot_measures_preview.json"))
    app = results_app.create_app(db_path=tmp_path / "results.sqlite3", catalog=lambda: (ELECTION, TITLES),
                                 clock=lambda: dt.datetime(2026, 10, 27, tzinfo=UTC))
    r = app.test_client().get("/results", headers=TOKEN).get_json()
    assert r["available"] and r["preview"] and len(r["measures"]) == 14
    assert (tmp_path / "results-preview.sqlite3").exists() and not (tmp_path / "results.sqlite3").exists()


def test_http_fetch_retries_with_backoff_then_gives_up(monkeypatch):
    calls, sleeps = [], []

    def fake_get(url, timeout, stream, headers):
        calls.append((url, timeout, headers["User-Agent"]))
        raise requests.ConnectTimeout()
    monkeypatch.setattr(results_app.requests, "get", fake_get)
    with pytest.raises(results_app.FetchError):
        http_fetch(sleep=sleeps.append)
    assert len(calls) == 3 and sleeps == [1.0, 2.0]
    assert calls[0][1] == (3.05, 8) and calls[0][0] == feed.SOURCE_URL


# ---------- the page ----------
def render_block(r, res, compact=False):
    from thinkballot.services.web.app import create_app
    app = create_app()
    with app.test_request_context("/"):
        macro = app.jinja_env.get_template("_results.html").module.results_block
        return str(macro(r, res, compact))


def sample_results(**changes):
    r = feed.parse(body(election_night()), ELECTION, TITLES)
    res = {"available": True, "status": "unofficial", "as_of_text": "November 3, 2026, 9:45 p.m. PT",
           "reporting": r["reporting"], "preview": False, "source_name": feed.SOURCE_NAME,
           "source_page": feed.SOURCE_PAGE, "source_url": feed.SOURCE_URL,
           "measures": {n: dict(m, yes_bar=float(m["yes_percent"]), no_bar=float(m["no_percent"]))
                        for n, m in r["measures"].items()}}
    res.update(changes)
    return res


@pytest.mark.parametrize("compact", [False, True])
def test_yes_and_no_get_identical_markup(compact):
    res = sample_results()
    html = render_block(res["measures"]["39"], res, compact)
    sides = re.findall(r'<div class="results-side">.*?</progress>', html, re.S)
    assert len(sides) == 2
    yes, no = sides
    assert "YES" in yes and "3,777" in yes and "(39.0%)" in yes
    assert "NO" in no and "5,902" in no and "(61.0%)" in no
    assert html.index("YES") < html.index(">NO<")  # YES first, as everywhere else
    blank = lambda s: re.sub(r"YES|NO|[\d,.]+", "#", s)  # noqa: E731
    assert blank(yes) == blank(no)  # same tags, classes and bar: only the label and numbers differ
    assert 'style=' not in html  # CSP: no inline styles
    assert "Unofficial results as of November 3, 2026, 9:45 p.m. PT" in html
    assert 'href="https://electionresults.sos.ca.gov/returns/ballot-measures"' in html
    for loaded in ["win", "lead", "pass", "fail", "landslide", "ahead", "behind"]:
        assert not re.search(rf"\b{loaded}", html, re.I), loaded


def test_block_shows_nothing_without_results():
    res = sample_results()
    assert render_block(None, res).strip() == ""
    assert render_block(res["measures"]["1"], {"available": False}).strip() == ""


def test_certified_and_preview_labels():
    res = sample_results(status="certified", preview=True)
    html = render_block(res["measures"]["1"], res)
    assert "Certified results as of" in html and "Unofficial" not in html
    assert "Preview with test data, not real results." in html


def test_ballot_page_shows_compact_results_only_when_available():
    from flask import render_template
    from thinkballot.services.web.app import create_app
    app = create_app()
    election = {"name": "November 3, 2026 California General Election", "date": ELECTION}
    measures = [{"id": "prop-39", "number": "39", "title": TITLES["39"], "summary": "S", "measure_type": None},
                {"id": "prop-45", "number": "45", "title": TITLES["45"], "summary": "S", "measure_type": None}]
    with app.test_request_context("/ballot"):
        html = render_template("ballot.html", election=election, measures=measures, place=None, local=None,
                               results=sample_results())
        assert html.count('class="results results-compact"') == 2
        none = render_template("ballot.html", election=election, measures=measures, place=None, local=None,
                               results=None)
        assert 'class="results' not in none


def test_pages_without_results_have_no_results_block(server):
    # The test server's clock is before election night (or its data has no matching feed): no box at all.
    for path in ["/ballot", "/prop/prop-a"]:
        html = requests.get(server + path).text
        assert 'class="results' not in html
    assert requests.get(server + "/svc/results/results", headers={"X-TB-Internal": config.INTERNAL_TOKEN}).json() == {"available": False}


def test_only_one_worker_claims_each_fetch(tmp_path):
    a = results_app.connect(tmp_path / "r.sqlite3")
    b = results_app.connect(tmp_path / "r.sqlite3")  # a second worker process's connection
    assert results_app.claim_attempt(a, 1000.0, 300) is True
    assert results_app.claim_attempt(b, 1001.0, 300) is False
    assert results_app.claim_attempt(b, 1300.0, 300) is True
