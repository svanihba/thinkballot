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


# ---------- phase 2 ----------

def ask(s, server, token, **body):
    return s.post(server + "/api/ask", json=dict(body, t=token), headers={"Sec-Fetch-Site": "same-origin"})


def test_ask_event_never_has_question_text(tracked):
    s = requests.Session()
    token = page_token(s.get(tracked + "/prop/prop-a").text)
    ask(s, tracked, token, measure_id="prop-a", question="my secret words")
    (e,) = of("ask")
    assert e["props"]["length"] == 15 and e["props"]["measure"] == "prop-a" and e["props"]["suggested"] is None
    assert e["props"]["status"] == 200 and e["props"]["outcome"] in ("answered", "refused", "held")
    assert isinstance(e["props"]["server_ms"], int)
    assert e["rid"] == of("pageview")[0]["rid"]
    assert not any("secret" in json.dumps(x) for x in events())


def test_suggested_ask_event(tracked):
    s = requests.Session()
    token = page_token(s.get(tracked + "/prop/prop-a").text)
    ask(s, tracked, token, measure_id="prop-a", question="What does it cost?", suggested=0)
    (e,) = of("ask")
    assert e["props"]["suggested"] == 0 and e["props"]["length"] == 0


def test_ask_event_on_bad_request(tracked):
    s = requests.Session()
    token = page_token(s.get(tracked + "/prop/prop-a").text)
    ask(s, tracked, token, measure_id="../etc", question="x")
    (e,) = of("ask")
    assert e["props"]["status"] == 400 and e["props"]["outcome"] == "bad_request"


def test_search_event_truncates_query(tracked):
    requests.get(tracked + "/search", params={"q": "b" * 300, "topic": "parks"})
    (e,) = of("search")
    assert e["props"]["q"] == "b" * 100 and e["props"]["topic"] == "parks" and isinstance(e["props"]["results"], int)


PHASE2 = [
    ({"type": "click", "props": {"name": "star", "kind": "button", "label": "☆ Star", "measure": "prop-a",
                                 "href": "/prop/prop-a", "rank": 3, "on": True}}, None),
    ({"type": "click", "props": {"name": "x" * 99, "kind": 5, "on": "yes", "rank": -1}}, {"name": "x" * 40}),
    ({"type": "select", "props": {"name": "measure-select", "value": "prop-b", "label": "Prop B", "measure": "prop-b"}}, None),
    ({"type": "scroll", "props": {"depth": 50}}, None),
    ({"type": "scroll", "props": {"depth": 33}}, {}),
    ({"type": "engaged", "props": {"ms": 12345}}, None),
    ({"type": "error", "props": {"message": "m" * 500, "source": "/static/app.js", "line": 12}},
     {"message": "m" * 200, "source": "/static/app.js", "line": 12}),
]


@pytest.mark.parametrize("raw,expected", PHASE2)
def test_phase2_client_events_cleaned(tracked, raw, expected):
    s = requests.Session()
    token = page_token(s.get(tracked + "/prop/prop-a").text)
    send(s, tracked, token, [raw])
    (e,) = of(raw["type"])
    assert e["props"] == (raw["props"] if expected is None else expected)


def test_track_names_present(tracked):
    s = requests.Session()
    measure = s.get(tracked + "/prop/prop-a").text
    for name in ["ask-submit", "suggest", "star", "share"]:
        assert f'data-track="{name}"' in measure, name
    assert 'data-track="lang-es"' in measure
    assert 'data-track="zip-submit"' in s.get(tracked + "/").text
    assert 'data-track="measure-select"' in s.get(tracked + "/ask").text
    results = s.get(tracked + "/search", params={"q": "bond"}).text
    assert 'data-track="search-result"' in results and 'data-rank="1"' in results


# ---------- browser side (static/app.js in Node, with a small stand-in page) ----------

TRACK_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const docListeners = {}, winListeners = {};
function node(tag, attrs, extra) {
  const n = Object.assign({ tagName: tag.toUpperCase(), dataset: {}, attributes: attrs || {}, textContent: "",
    parent: null, className: "", id: "",
    getAttribute(k) { return this.attributes[k] == null ? null : this.attributes[k]; },
    closest(sel) {
      const want = sel.split(",").map((s) => s.trim());
      for (let n = this; n; n = n.parent) if (want.some((w) => matches(n, w))) return n;
      return null;
    } }, extra || {});
  return n;
}
function matches(n, w) {
  const m = w.match(/^([a-z]+)?(?:\[([a-z-]+)(?:=([a-z]+))?\])?$/);
  if (!m) return false;
  if (m[1] && n.tagName !== m[1].toUpperCase()) return false;
  if (m[2]) {
    const v = m[2].startsWith("data-") ? n.dataset[m[2].slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())]
      : n.attributes[m[2]];
    if (v == null) return false;
    if (m[3] && v !== m[3]) return false;
  }
  return true;
}
const body = { dataset: { prefix: "/es", et: "rid.1.sig", i18n: "{}" } };
const document = {
  body, visibilityState: "visible", documentElement: { scrollHeight: 2000 }, readyState: "loading",
  addEventListener(t, f) { (docListeners[t] = docListeners[t] || []).push(f); },
  querySelector() { return null; }, querySelectorAll() { return []; },
  createElement() { return { set textContent(v) {}, get innerHTML() { return ""; } }; },
};
const ctx = {
  document, console, JSON, Math, Date, String, Number, URL, setTimeout, clearTimeout, setInterval: () => 0,
  navigator: {}, location: { pathname: "/es/prop/prop-a", href: "https://www.example.org/es/prop/prop-a",
                             origin: "https://www.example.org" },
  localStorage: { getItem() {}, setItem() {} }, performance: { getEntriesByType: () => [] },
  innerWidth: 390, innerHeight: 800, scrollY: 0,
  addEventListener(t, f) { (winListeners[t] = winListeners[t] || []).push(f); },
  fetch: async () => ({}),
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
vm.runInContext("initAnalytics()", ctx);
const fire = (t, target) => (docListeners[t] || []).forEach((f) => f({ target }));
const card = node("article", {}, { dataset: { measure: "prop-b" } });
const star = node("button", { "aria-pressed": "true" }, { dataset: { track: "star" }, className: "star", textContent: "  ★ Starred " , parent: card });
const out = node("a", { href: "https://www.sos.ca.gov/guide?x=1" }, { href: "https://www.sos.ca.gov/guide?x=1", className: "src", textContent: "[1]" });
const inner = node("a", { href: "/es/prop/prop-c#argument-for" }, { href: "https://www.example.org/es/prop/prop-c#argument-for", textContent: "Prop C" });
const span = node("span", {}, { parent: inner });
const sel = node("select", {}, { dataset: { track: "measure-select" }, value: "prop-d", selectedIndex: 0,
  options: [{ text: "Prop D: Parks" }] });
const box = node("input", { type: "checkbox" }, { type: "checkbox", checked: true, id: "agree", labels: [{ textContent: "I agree" }] });
const text = node("input", { type: "text" }, { type: "text", value: "my secret", className: "q" });
const sug = node("button", {}, { dataset: { track: "suggest", index: "2" }, className: "suggest", textContent: "Who pays?" });
fire("click", star); fire("click", out); fire("click", span); fire("click", box); fire("click", text); fire("click", sug);
const lean = node("select", {}, { name: "leaning", value: "left", selectedIndex: 0, options: [{ text: "Left" }] });
fire("change", sel); fire("change", text); fire("change", lean);
ctx.scrollY = 1300; (winListeners.scroll || []).forEach((f) => f());
(winListeners.error || []).forEach((f) => f({ message: "boom", filename: "https://www.example.org/static/app.js", lineno: 7 }));
setTimeout(() => console.log(JSON.stringify(vm.runInContext("queue", ctx))), 10);
"""


@pytest.fixture(scope="module")
def tracked_js(tmp_path_factory):
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed")
    harness = tmp_path_factory.mktemp("js") / "track.js"
    harness.write_text(TRACK_HARNESS)
    app_js = config.ROOT / "thinkballot" / "services" / "web" / "static" / "app.js"
    run = subprocess.run(["node", str(harness), str(app_js)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return [(e["type"], e["props"]) for e in json.loads(run.stdout)]


def test_browser_logs_every_control(tracked_js):
    clicks = [p for t, p in tracked_js if t == "click"]
    assert clicks[0] == {"name": "star", "kind": "button", "label": "★ Starred", "measure": "prop-b", "on": True}
    assert clicks[1] == {"name": "src", "kind": "a", "label": "[1]", "measure": "prop-a", "href": "www.sos.ca.gov"}
    assert clicks[2] == {"name": "a", "kind": "a", "label": "Prop C", "measure": "prop-c",
                         "href": "/prop/prop-c#argument-for"}
    assert clicks[3] == {"name": "agree", "kind": "checkbox", "label": "I agree", "measure": "prop-a", "on": True}
    assert clicks[4] == {"name": "suggest", "kind": "button", "label": "Who pays?", "measure": "prop-a", "rank": 2}
    assert len(clicks) == 5  # the click in the text box is not logged
    assert ("select", {"name": "measure-select", "value": "prop-d", "label": "Prop D: Parks", "measure": "prop-a"}) \
        in tracked_js
    assert [p["depth"] for t, p in tracked_js if t == "scroll"] == [25, 50, 75, 100]
    assert ("error", {"message": "boom", "source": "/static/app.js", "line": 7}) in tracked_js
    assert ("select", {"name": "leaning", "measure": "prop-a"}) in tracked_js  # no value for unnamed dropdowns
    assert "my secret" not in json.dumps(tracked_js) and "Left" not in json.dumps(tracked_js)


def test_privacy_text_covers_phase2(server):
    html = requests.get(server + "/neutral").text
    for phrase in ["how far you scroll", "menus and other controls", "never what you type into them", "errors"]:
        assert phrase in html
