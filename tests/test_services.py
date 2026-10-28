"""The services working together over HTTP, as they run in production."""

import re

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


def session_with_token(server):
    s = requests.Session()
    token = re.search(r'name="csrf" value="([^"]+)"', s.get(server + "/").text).group(1)
    return s, token


def test_sample_zip_shows_likely_districts(server):
    s, token = session_with_token(server)
    html = s.post(server + "/ballot", data={"csrf": token, "zip": "94087"}).text
    assert "Your likely districts, based on ZIP code 94087" in html
    assert "Congressional District 17" in html


def test_unknown_zip_still_shows_statewide_ballot(server):
    s, token = session_with_token(server)
    html = s.post(server + "/ballot", data={"csrf": token, "zip": "96000"}).text
    assert "couldn't match ZIP code 96000" in html and "Sample Park Bond" in html


def test_zip_box_offers_only_known_zip_codes(server):
    landing = requests.get(server + "/").text
    assert 'list="zip-list"' in landing and '<datalist id="zip-list">' in landing
    zips = requests.get(server + "/api/zips").json()["zips"]
    assert ["94087", "Sunnyvale"] in zips and "96000" not in [z for z, _ in zips]
    assert [z for z, _ in zips] == sorted(z for z, _ in zips)


def test_text_that_is_not_a_zip_code_is_explained(server):
    s, token = session_with_token(server)
    html = s.post(server + "/ballot", data={"csrf": token, "zip": "Sunnyvale"}).text
    assert "isn't a California ZIP code" in html and "Sample Park Bond" in html


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


def test_forms_without_a_session_token_are_rejected(server):
    assert requests.post(server + "/ballot", data={"zip": "94087"}).status_code == 400
    assert requests.post(server + "/ballot", data={"csrf": "", "zip": "94087"}).status_code == 400


def test_sign_in_redirect_stays_on_this_site(server):
    s, token = session_with_token(server)
    for bad in ["//evil.com", "/\\evil.com", "https://evil.com", "/\tevil.com"]:
        r = s.post(server + "/signin", data={"csrf": token, "action": "signin", "email": "x@example.com",
                                             "password": "nope", "next": bad}, allow_redirects=False)
        assert "evil.com" not in r.headers.get("Location", ""), bad


def test_measure_ids_are_validated(server):
    assert requests.get(server + "/prop/x%3Fviewer=5").status_code == 404
    r = requests.post(server + "/api/ask", json={"measure_id": "../../community/moderation?user_id=1",
                                                 "question": "hi"})
    assert r.status_code == 400


def test_phone_friendly_form_attributes(server):
    landing = requests.get(server + "/").text
    zip_input = re.search(r'<input type="text" name="zip"[^>]*>', landing).group(0)
    assert 'enterkeyhint="go"' in zip_input
    assert 'inputmode="numeric"' in zip_input and 'autocomplete="postal-code"' in zip_input
    assert "address" not in landing.lower()  # the home page asks only for a ZIP code
    ask = requests.get(server + "/prop/prop-a").text
    question = re.search(r'<input type="text" name="question"[^>]*>', ask).group(0)
    assert 'enterkeyhint="send"' in question
    assert 'enterkeyhint="search"' in requests.get(server + "/search").text


def test_stacked_arguments_announce_both_sides_in_order(server):
    html = requests.get(server + "/prop/prop-a").text
    jump = re.search(r'<nav class="side-jump".*?</nav>', html, re.S).group(0)
    assert jump.index('href="#argument-for"') < jump.index('href="#argument-against"')
    assert html.index('id="argument-for"') < html.index('id="argument-against"')
