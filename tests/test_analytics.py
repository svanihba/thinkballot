"""Visitor analytics: what the web service logs, for whom, and what it refuses to log."""

import email.utils
import json
import re
import time

import pytest
import requests
from flask import Flask
from flask.sessions import SecureCookieSessionInterface

from thinkballot import config
from thinkballot.services.web import analytics


@pytest.fixture
def tracked(server, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANALYTICS", "force")
    monkeypatch.setattr(config, "EVENT_LOG_DIR", tmp_path / "events")
    from thinkballot import ratelimit
    ratelimit.allow("events", "warm-up", [(1, 1)])  # creates the table on a fresh database
    from test_verification import reset_limits
    reset_limits()
    return server


def events():
    rows = []
    for path in sorted(config.EVENT_LOG_DIR.glob("events-*.jsonl")) if config.EVENT_LOG_DIR.exists() else []:
        rows += [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    return rows


def of(type_):
    return [e for e in events() if e["type"] == type_]


def cookie_session(resp_or_session):
    jar = resp_or_session.cookies
    raw = jar.get("session")
    if not raw:
        return {}
    app = Flask("decode")
    app.secret_key = config.SECRET_KEY
    return SecureCookieSessionInterface().get_signing_serializer(app).loads(raw)


def page_token(html):
    m = re.search(r'data-et="([^"]+)"', html)
    return m and m.group(1)


def csrf(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def test_page_view_is_logged_with_cookie_id(tracked):
    s = requests.Session()
    s.get(tracked + "/prop/prop-a?src=ig&utm_campaign=launch")
    s.get(tracked + "/about")
    views = of("pageview")
    assert len(views) == 2
    first = views[0]
    assert len(first["aid"]) == 22 and first["rid"] and first["v"] == 1
    assert first["path"] == "/prop/prop-a" and first["lang"] == "en"
    assert first["props"]["measure"] == "prop-a"
    assert first["props"]["src"] == "ig" and first["props"]["utm_campaign"] == "launch"
    assert isinstance(first["props"]["server_ms"], int)
    assert views[1]["aid"] == first["aid"] and views[1]["rid"] != first["rid"]


def test_language_is_logged(tracked):
    requests.get(tracked + "/es/about")
    assert of("pageview")[0]["lang"] == "es" and of("pageview")[0]["path"] == "/about"


def test_session_cookie_lasts_60_days(tracked):
    resp = requests.get(tracked + "/about")
    header = resp.headers["Set-Cookie"]
    expires = email.utils.parsedate_to_datetime(re.search(r"Expires=([^;]+)", header).group(1)).timestamp()
    assert abs(expires - (time.time() + 60 * 86400)) < 3600


def test_zip_is_logged_but_nothing_else_from_the_box(tracked):
    s = requests.Session()
    token = csrf(s.get(tracked + "/").text)
    s.post(tracked + "/ballot", data={"csrf": token, "zip": "94087"})
    s.post(tracked + "/ballot", data={"csrf": token, "zip": "1 Main St 94087"})
    s.post(tracked + "/ballot", data={"csrf": token, "zip": "hello"})
    subs = of("zip_submit")
    assert [(e["props"]["zip"], e["props"]["accepted"]) for e in subs] == [
        ("94087", True), ("94087", True), (None, False)]
    ballot_views = [e for e in of("pageview") if e["path"] == "/ballot"]
    assert ballot_views[0]["props"]["zip"] == "94087"
    assert not any("Main St" in json.dumps(e) for e in events())


@pytest.mark.parametrize("header", [{"Sec-GPC": "1"}, {"DNT": "1"}])
def test_gpc_and_dnt_mean_nothing_logged_and_no_id(tracked, header):
    s = requests.Session()
    s.headers.update(header)
    resp = s.get(tracked + "/")
    assert "aid" not in cookie_session(resp)
    assert page_token(resp.text) is None
    s.post(tracked + "/api/e", json={"t": "x.1.y", "events": [{"type": "timing", "props": {}}]})
    assert events() == []


def test_not_production_logs_nothing(tracked, monkeypatch):
    monkeypatch.setattr(config, "ANALYTICS", "1")  # the test server is not the production copy
    resp = requests.get(tracked + "/about")
    assert events() == [] and page_token(resp.text) is None


def test_off_switch(tracked, monkeypatch):
    monkeypatch.setattr(config, "ANALYTICS", "0")
    requests.get(tracked + "/about")
    assert events() == []


def test_public_cached_responses_set_no_cookie(tracked):
    for path in ["/api/zips", "/robots.txt", "/sitemap.xml", "/static/app.js", "/api/health"]:
        resp = requests.get(tracked + path)
        assert "Set-Cookie" not in resp.headers, path
    assert events() == []


def send(s, server, token, evs, page="/prop/prop-a"):
    return s.post(server + "/api/e", json={"t": token, "p": page, "events": evs},
                  headers={"Sec-Fetch-Site": "same-origin"})


def test_client_events_are_cleaned(tracked):
    s = requests.Session()
    token = page_token(s.get(tracked + "/prop/prop-a").text)
    aid = of("pageview")[0]["aid"]
    good = {"type": "timing", "ts": 1761800000000, "props": {"ttfb": 120, "dom": 800, "load": 1500, "vw": 390,
                                                              "vh": 844}}
    hostile = {"type": "timing", "props": {"ttfb": "fast", "aid": "x", "dom": True, "load": -5, "note": "a" * 10000}}
    assert send(s, tracked, token, [good, {"type": "nope", "props": {}}, hostile]).status_code == 204
    assert send(s, tracked, token, [good] * 21).status_code == 400
    timings = of("timing")
    assert len(timings) == 2
    assert timings[0]["props"] == good["props"] and timings[0]["client_ts"] == good["ts"]
    assert timings[1]["props"] == {}
    assert all(e["aid"] == aid and e["rid"] == of("pageview")[0]["rid"] for e in timings)
    assert timings[0]["path"] == "/prop/prop-a"


def test_api_e_without_page_view_logs_nothing(tracked):
    resp = requests.post(tracked + "/api/e", json={"t": "a.1.b", "events": [{"type": "timing"}]})
    assert resp.status_code == 204 and events() == []


def test_event_token_must_verify(tracked):
    s = requests.Session()
    token = page_token(s.get(tracked + "/about").text)
    aid = cookie_session(s)["aid"]
    rid, issued, _mac = token.split(".")
    now = int(time.time())
    bad = [rid + "x." + issued + "." + _mac,                          # changed page load
           analytics.sign_token(rid, "someone-else", now),           # signed for another visitor
           analytics.sign_token(rid, aid, now - 13 * 3600),          # expired
           None]
    for t in bad:
        send(s, tracked, t, [{"type": "timing", "props": {"ttfb": 1}}])
    assert of("timing") == []
    send(s, tracked, token, [{"type": "timing", "props": {"ttfb": 1}}])
    assert len(of("timing")) == 1


def test_event_batches_capped_per_page_load(tracked):
    s = requests.Session()
    token = page_token(s.get(tracked + "/about").text)
    for _ in range(61):
        send(s, tracked, token, [{"type": "timing", "props": {"ttfb": 1}}])
    assert len(of("timing")) == 60


def test_signout_keeps_visitor_id(tracked):
    s = requests.Session()
    html = s.get(tracked + "/about").text
    before = cookie_session(s)["aid"]
    s.post(tracked + "/signout", data={"csrf": csrf(s.get(tracked + "/").text)})
    assert cookie_session(s)["aid"] == before


def test_visitor_id_renewed_after_60_days(tracked):
    app = Flask("encode")
    app.secret_key = config.SECRET_KEY
    old = SecureCookieSessionInterface().get_signing_serializer(app).dumps(
        {"aid": "old-visitor-number-xxxx", "aid_t": int(time.time()) - 61 * 86400})
    s = requests.Session()
    s.cookies.set("session", old)
    s.get(tracked + "/about")
    assert of("pageview")[0]["aid"] != "old-visitor-number-xxxx"


def test_logging_failure_does_not_break_pages(tracked, tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(config, "EVENT_LOG_DIR", blocker)
    assert requests.get(tracked + "/prop/prop-a").status_code == 200


def test_events_lines_follow_schema(tracked):
    s = requests.Session()
    token = page_token(s.get(tracked + "/").text)
    s.post(tracked + "/ballot", data={"csrf": csrf(s.get(tracked + "/").text), "zip": "94087"})
    send(s, tracked, token, [{"type": "timing", "props": {"ttfb": 5}}])
    rows = events()
    assert rows
    for e in rows:
        assert e["v"] == 1 and isinstance(e["ts"], int) and isinstance(e["type"], str)
        assert isinstance(e["aid"], str) and isinstance(e["props"], dict)
        assert e["device"] in ("phone", "tablet", "desktop") and e["bot"] in (0, 1)
        assert not {"question", "ip", "user", "email", "username"} & (set(e) | set(e["props"]))


# ---------- AI request events ----------

class FakeResponse:
    def __init__(self, status, content='{"ok": true}'):
        self.status_code = status
        self._body = {"provider": "FastHost", "choices": [{"message": {"content": content}}],
                      "usage": {"prompt_tokens": 1200, "completion_tokens": 300, "cost": 0.0042,
                                "prompt_tokens_details": {"cached_tokens": 1000}}}

    def json(self):
        return self._body


@pytest.fixture
def live_ai(tracked, monkeypatch):
    from thinkballot import ai
    monkeypatch.setattr(config, "AI_PROVIDER", "openrouter")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key-not-real")
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)
    sent = []

    def fake_post(payload, headers, timeout):
        sent.append(payload)
        return replies.pop(0) if replies else FakeResponse(200)
    replies = []
    monkeypatch.setattr(ai, "_post", fake_post)
    return ai, replies, sent


def test_ai_event_per_attempt(live_ai):
    ai, replies, sent = live_ai
    ai.chat_json("some/model", "system words", "user words", purpose="answer", meta={"measure": "prop-a", "lang": "es"})
    (e,) = of("ai")
    assert e["props"] == {"purpose": "answer", "model": "some/model", "provider": "FastHost", "attempt": 1,
                          "status": 200, "ms": e["props"]["ms"], "in_tok": 1200, "out_tok": 300, "cached_tok": 1000,
                          "cost": 0.0042, "measure": "prop-a", "lang": "es"}
    assert "aid" not in e and e["rid"] is None
    assert "system words" not in json.dumps(e) and "user words" not in json.dumps(e)
    assert sent[0]["usage"] == {"include": True}


def test_ai_event_on_error_status(live_ai):
    ai, replies, _ = live_ai
    replies.append(FakeResponse(503))
    ai.chat_json("some/model", "s", "u", purpose="review")
    assert [e["props"]["status"] for e in of("ai")] == [503, 200]
    assert [e["props"]["attempt"] for e in of("ai")] == [1, 2]


def test_ai_event_carries_rid_of_tracked_visitor(live_ai):
    s = requests.Session()
    token = page_token(s.get(config.PUBLIC_BASE + "/prop/prop-a").text)
    rid = of("pageview")[0]["rid"]
    s.post(config.PUBLIC_BASE + "/api/ask", json={"measure_id": "prop-a", "question": f"what does it cost {time.time()}",
                                                  "t": token}, headers={"Sec-Fetch-Site": "same-origin"})
    ai_lines = of("ai")
    assert ai_lines and all(e["rid"] == rid for e in ai_lines)
    assert all(e["props"]["measure"] == "prop-a" for e in ai_lines if e["props"]["purpose"] == "answer")


def test_ai_event_has_no_rid_for_gpc_visitor(live_ai):
    s = requests.Session()
    s.headers["Sec-GPC"] = "1"
    s.get(config.PUBLIC_BASE + "/prop/prop-a")
    s.post(config.PUBLIC_BASE + "/api/ask", json={"measure_id": "prop-a", "question": f"who pays {time.time()}"},
           headers={"Sec-Fetch-Site": "same-origin"})
    ai_lines = of("ai")
    assert ai_lines and all(e["rid"] is None and "aid" not in e for e in ai_lines)


def test_stub_ai_logs_nothing(tracked):
    from thinkballot import ai
    ai.chat_json("some/model", "s", "u", stub=lambda u: {"ok": True}, purpose="answer")
    assert of("ai") == []


def test_privacy_text_describes_analytics(server):
    html = requests.get(server + "/neutral").text
    for phrase in ["60 days", "Global Privacy Control", "typed questions are not"]:
        assert phrase in html
    from thinkballot.services.web import i18n
    for lang in ("es", "zh"):
        page = requests.get(server + f"/{lang}/neutral").text
        assert "Global Privacy Control" in page  # the name stays as is in every language
        assert "60" in page and "visitor number" not in page


# ---------- review fixes ----------

def test_cached_and_api_responses_set_no_cookie_for_a_returning_visitor(tracked):
    s = requests.Session()
    s.get(tracked + "/about")
    assert cookie_session(s).get("aid")
    for path in ["/api/zips", "/robots.txt", "/static/app.js", "/api/health"]:
        assert "Set-Cookie" not in s.get(tracked + path).headers, path
    token = page_token(s.get(tracked + "/about").text)
    assert "Set-Cookie" not in send(s, tracked, token, [{"type": "timing", "props": {"ttfb": 1}}]).headers


def test_page_views_keep_the_cookie_fresh(tracked):
    s = requests.Session()
    s.get(tracked + "/about")
    assert "Set-Cookie" in s.get(tracked + "/about").headers  # the 60 days slide with each page


@pytest.mark.parametrize("token", ["a." + "9" * 5000 + ".b", "a.1.é", "a.1." + "x" * 22 + "é", 12, ["x"]])
def test_hostile_tokens_never_break_a_request(tracked, token):
    s = requests.Session()
    s.get(tracked + "/about")
    assert send(s, tracked, token, [{"type": "timing"}]).status_code == 204
    r = s.post(tracked + "/api/ask", json={"measure_id": "prop-a", "question": "what does it do", "t": token},
               headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code != 500


@pytest.mark.parametrize("ev", [{"type": ["timing"]}, {"type": {"a": 1}}, {"type": None}, "timing", 5,
                                {"type": "timing", "ts": 10 ** 400}])
def test_hostile_events_never_break_a_batch(tracked, ev):
    s = requests.Session()
    token = page_token(s.get(tracked + "/about").text)
    assert send(s, tracked, token, [ev, {"type": "timing", "props": {"ttfb": 7}}]).status_code == 204
    timings = of("timing")
    assert timings[-1]["props"] == {"ttfb": 7}
    assert all(e["client_ts"] is None or 0 <= e["client_ts"] < 2 ** 53 for e in timings)


def test_bad_referrer_still_logs_the_page_view(tracked):
    requests.get(tracked + "/about", headers={"Referer": "http://[bad"})
    assert len(of("pageview")) == 1 and "ref" not in of("pageview")[0]["props"]


def test_turning_on_gpc_removes_the_visitor_number(tracked):
    s = requests.Session()
    s.get(tracked + "/about")
    assert cookie_session(s).get("aid")
    s.headers["Sec-GPC"] = "1"
    s.get(tracked + "/about")
    assert "aid" not in cookie_session(s)


def test_privacy_text_names_everything_recorded(server):
    html = requests.get(server + "/neutral").text
    for phrase in ["operating system", "screen size", "nothing about your visit is recorded"]:
        assert phrase in html


def test_turning_on_gpc_never_sets_a_cookie_on_a_cached_response(tracked):
    s = requests.Session()
    s.get(tracked + "/about")
    s.headers["Sec-GPC"] = "1"
    assert "Set-Cookie" not in s.get(tracked + "/api/zips").headers
    s.get(tracked + "/about")
    assert "aid" not in cookie_session(s)
