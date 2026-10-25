"""The services working together over HTTP, as they run in production."""

import requests

from thinkballot.services.geo.app import extract_zip


def test_extract_zip():
    assert extract_zip("Mango Park, Sunnyvale, 94087") == "94087"
    assert extract_zip("1 Main St, Sunnyvale CA 94087-1234") == "94087"
    assert extract_zip("10001 New York") is None


def test_pages_render(server):
    for path in ["/", "/ballot", "/prop/prop-a", "/prop/prop-b", "/neutral", "/about", "/search", "/ask",
                 "/ask?measure=prop-b", "/search?q=bonds&topic=parks"]:
        assert requests.get(server + path).status_code == 200, path
    assert requests.get(server + "/prop/nope").status_code == 404


def test_missing_field_is_labelled_not_invented(server):
    html = requests.get(server + "/prop/prop-b").text
    assert "Not available in the official guide." in html


def test_sample_address_shows_likely_districts(server):
    html = requests.post(server + "/ballot", data={"address": "Mango Park, Sunnyvale, 94087"}).text
    assert "Your likely districts, based on ZIP code 94087" in html
    assert "Congressional District 17" in html


def test_unknown_zip_still_shows_statewide_ballot(server):
    html = requests.post(server + "/ballot", data={"address": "somewhere 96000"}).text
    assert "couldn't match" in html and "Sample Park Bond" in html


def test_ask_answers_with_a_checked_quote(server):
    r = requests.post(server + "/api/ask", json={"measure_id": "prop-a", "question": "What does it do?"}).json()
    assert r["status"] == "answered" and r["verdict"] == "pass"
    assert r["points"][0]["source_url"].startswith("https://")
    assert r["points"][0]["quote"] in requests.get(server + "/prop/prop-a").text


def test_ask_never_says_how_to_vote(server):
    r = requests.post(server + "/api/ask", json={"measure_id": "prop-a", "question": "How should I vote?"}).json()
    assert r["status"] == "refused" and "never tells anyone how to vote" in r["reason"]


def test_search_matches_text_and_filters_by_topic(server):
    r = requests.get(server + "/svc/search/search", params={"q": "bonds"}).json()
    assert [m["id"] for m in r["results"]] == ["prop-b"]
    r = requests.get(server + "/svc/search/search", params={"topic": "libraries"}).json()
    assert [m["id"] for m in r["results"]] == ["prop-a"]
    assert "parks" in r["topics"]
