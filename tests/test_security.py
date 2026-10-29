"""Hardening: login timing and limits, the two kinds of 429, same-origin JSON posts."""

import re

import pytest
import requests

from thinkballot import config
from thinkballot.servicekit import ServiceClient, ServiceError


def test_unknown_email_still_checks_a_password_hash(server, monkeypatch):
    from thinkballot.services.community import app as community_app
    checked = []
    real = community_app.check_password_hash
    monkeypatch.setattr(community_app, "check_password_hash", lambda h, p: checked.append(h) or real(h, p))
    with pytest.raises(ServiceError) as exc:
        ServiceClient("community").post("/login", {"email": "nobody-here@example.com", "password": "password123"})
    assert exc.value.status == 401 and checked == [community_app.DUMMY_PW_HASH]


def test_sign_in_attempts_are_limited_per_email_across_addresses(server):
    s = requests.Session()
    csrf = re.search(r'name="csrf" value="([^"]+)"', s.get(server + "/signin").text).group(1)

    def attempt(email, n):
        return s.post(server + "/signin", data={"csrf": csrf, "action": "signin", "email": email, "password": "x"},
                      headers={"X-Forwarded-For": f"10.77.{n}.1"}).text
    for n in range(10):  # a different client address each time, so only the email bucket can stop it
        assert "Wrong email or password" in attempt("Target@Example.com", n)
    assert "Too many attempts" in attempt("target@example.com", 11)
    assert "Wrong email or password" in attempt("someone-else@example.com", 12)


ASK = {"measure_id": "prop-a", "question": "Something typed that is not suggested?"}


def test_site_wide_cap_and_visitor_limit_are_told_apart(server, monkeypatch):
    monkeypatch.setattr(config, "ASK_LIMITS_SITEWIDE", [(0, 60)])
    r = requests.post(server + "/api/ask", json=ASK)
    assert r.status_code == 429 and "answering a lot of questions" in r.json()["reason"]
    r = requests.post(server + "/es/api/ask", json=ASK)
    assert r.status_code == 429 and "muchas preguntas" in r.json()["reason"]
    monkeypatch.setattr(config, "ASK_LIMITS_PER_CLIENT", [(0, 60)])
    r = requests.post(server + "/api/ask", json=ASK)
    assert r.status_code == 429 and "Too many questions in a minute" in r.json()["reason"]


def test_json_posts_must_be_same_origin(server):
    for site in ("cross-site", "same-site", "none"):
        r = requests.post(server + "/api/ask", json=ASK, headers={"Sec-Fetch-Site": site})
        assert r.status_code == 403, site
    r = requests.post(server + "/api/ask", json=ASK, headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200
    assert requests.post(server + "/api/ask", json=ASK).status_code == 200  # no header: not a browser


def _count_ballot_calls(monkeypatch):
    calls = []
    real = ServiceClient.get
    monkeypatch.setattr(ServiceClient, "get", lambda self, path, **kw: calls.append(path) or real(self, path, **kw))
    return calls


def test_search_and_sitemap_read_the_ballot_data_once(server, monkeypatch):
    token = {"X-TB-Internal": config.INTERNAL_TOKEN}
    requests.get(server + "/svc/search/search", params={"q": "bonds"}, headers=token)  # loads the corpus
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    first = requests.get(server + "/sitemap.xml").text
    calls = _count_ballot_calls(monkeypatch)
    for _ in range(3):
        assert requests.get(server + "/svc/search/search", params={"q": "parks"}, headers=token).status_code == 200
        assert requests.get(server + "/sitemap.xml").text == first
    assert calls == []
