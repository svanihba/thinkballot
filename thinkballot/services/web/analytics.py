"""Visitor analytics for the web service: who opens which pages and uses which controls, as event lines.

Only logging lives here; the files are copied and analysed by a separate system. A visitor number (aid) is
kept in the site's session cookie for at most 60 days and is never tied to an account. Each tracked page
carries a server-signed token naming its page load (rid); browser events are logged only with a valid token,
so every event belongs to a page this site served to that cookie. Browsers that send Global Privacy Control
or Do Not Track get no visitor number and nothing is logged for them.
"""

import base64
import datetime as dt
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import urlsplit

from flask import g, jsonify, request, session

from ... import config, eventlog, ratelimit

PAGE_ENDPOINTS = {"landing", "ballot_page", "measure_page", "search_page", "ask_page", "neutral", "about"}
TOKEN_SECONDS = 12 * 3600
MAX_EVENTS, MAX_BODY = 20, 16 * 1024
BATCHES_PER_PAGE, BATCHES_PER_NETWORK_HOUR = 60, 600

TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{1,16}\.[0-9]{1,12}\.[A-Za-z0-9_-]{22}")
BOT_RE = re.compile(r"bot|crawl|spider|slurp|preview|monitor|curl|wget|python-requests|httpclient|headless", re.I)
BROWSERS = [("Edge", "Edg"), ("Opera", "OPR/"), ("Samsung", "SamsungBrowser"), ("Firefox", "Firefox/"),
            ("Firefox", "FxiOS"), ("Chrome", "CriOS"), ("Chrome", "Chrome/"), ("Safari", "Safari/")]
SYSTEMS = [("iOS", re.compile(r"iPhone|iPad|iPod")), ("Android", re.compile("Android")),
           ("Windows", re.compile("Windows")), ("ChromeOS", re.compile("CrOS")),
           ("macOS", re.compile("Macintosh|Mac OS X")), ("Linux", re.compile("Linux"))]

# What a browser may send, per event type: prop -> (int, max), (bool, None), (str, max length) or a set of values.
CLIENT_EVENTS = {
    "timing": {"ttfb": (int, 600_000), "dom": (int, 600_000), "load": (int, 600_000), "vw": (int, 20_000),
               "vh": (int, 20_000)},
    "click": {"name": (str, 40), "kind": (str, 16), "label": (str, 80), "measure": (str, 40), "href": (str, 120),
              "rank": (int, 1000), "on": (bool, None)},
    "select": {"name": (str, 40), "value": (str, 80), "label": (str, 80), "measure": (str, 40)},
    "scroll": {"depth": frozenset({25, 50, 75, 100})},
    "engaged": {"ms": (int, 86_400_000)},
    "error": {"message": (str, 200), "source": (str, 120), "line": (int, 10_000_000)},
}


def opted_out():
    return request.headers.get("Sec-GPC") == "1" or request.headers.get("DNT") == "1"


def tracking():
    if "an_tracking" not in g:
        g.an_tracking = eventlog.enabled() and not opted_out()
    return g.an_tracking


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _mac(rid, aid, issued):
    digest = hmac.new(config.SECRET_KEY.encode(), f"{rid}|{aid}|{issued}".encode(), hashlib.sha256).digest()
    return _b64(digest)[:22]


def sign_token(rid, aid, issued):
    return f"{rid}.{issued}.{_mac(rid, aid, issued)}"


def verify_token(token, aid, now):
    """The page load (rid) a token names, if the server signed it for this visitor in the last 12 hours."""
    if not isinstance(token, str) or not aid or not TOKEN_RE.fullmatch(token):
        return None
    parts = token.split(".")
    rid, issued = parts[0], int(parts[1])
    if not 0 <= now - issued <= TOKEN_SECONDS:
        return None
    return rid if hmac.compare_digest(parts[2], _mac(rid, aid, issued)) else None


def client_info():
    ua = request.headers.get("User-Agent", "")
    browser = next((name for name, mark in BROWSERS if mark in ua), "other")
    system = next((name for name, pat in SYSTEMS if pat.search(ua)), "other")
    if re.search(r"iPad|Tablet", ua) or ("Android" in ua and "Mobile" not in ua):
        device = "tablet"
    elif re.search(r"Mobi|iPhone|Android", ua):
        device = "phone"
    else:
        device = "desktop"
    return {"browser": browser, "os": system, "device": device, "bot": 1 if not ua or BOT_RE.search(ua) else 0}


def _event(type_, props, rid, path=None):
    ev = {"ts": int(time.time() * 1000), "aid": session.get("aid"), "rid": rid, "type": type_,
          "path": path or request.path, "lang": getattr(g, "lang", "en")}
    ev.update(client_info())
    ev["props"] = props or {}
    return ev


def log(type_, props=None):
    """A server-side event for this request's page load; nothing when the visitor isn't tracked."""
    if tracking() and session.get("aid") and g.get("rid"):
        eventlog.log_event(_event(type_, props, g.rid))


def adopt_token(token):
    """A JSON call made by a tracked page (Ask): take its page load from the page's signed token."""
    try:
        if tracking():
            rid = verify_token(token, session.get("aid"), int(time.time()))
            if rid:
                g.rid = rid
                eventlog.current_rid.set(rid)
    except Exception:  # noqa: BLE001 - analytics never breaks an answer
        pass


def note_ask(body, status, result, started):
    """The outcome of one Ask request (never the question's text)."""
    try:
        question = body.get("question") if isinstance(body, dict) else None
        suggested = body.get("suggested") if isinstance(body, dict) and type(body.get("suggested")) is int else None
        result = result if isinstance(result, dict) else {}
        if status == 400:
            outcome = "bad_request"
        elif status == 429:
            outcome = "limited"
        elif status != 200:
            outcome = "error"
        elif result.get("status") == "answered" and result.get("prepared"):
            outcome = "prepared"
        else:
            outcome = str(result.get("status") or "error")[:16]
        measure = body.get("measure_id") if isinstance(body, dict) and isinstance(body.get("measure_id"), str) else None
        log("ask", {"measure": (measure or "")[:40] or None, "suggested": suggested,
                    "length": 0 if suggested is not None or not isinstance(question, str) else len(question),
                    "outcome": outcome, "status": status, "server_ms": int((time.monotonic() - started) * 1000),
                    "translated": bool(result.get("translated")), "verdict": result.get("verdict")})
    except Exception:  # noqa: BLE001 - analytics never breaks an answer
        pass


def note_zip(zip_code, accepted):
    """The ZIP box was used: log the 5-digit ZIP found in it (nothing else) and whether it was accepted."""
    g.an_zip = zip_code
    log("zip_submit", {"zip": zip_code, "accepted": bool(accepted)})


def _ensure_visitor():
    now = int(time.time())
    if not session.get("aid") or now - int(session.get("aid_t", 0)) > config.SESSION_DAYS * 86400:
        session["aid"], session["aid_t"] = secrets.token_urlsafe(16), now
    session.permanent = True


def _clean_value(kind, value):
    if isinstance(kind, (set, frozenset)):
        return value if value in kind and not isinstance(value, bool) else None
    typ, limit = kind
    if typ is bool:
        return value if isinstance(value, bool) else None
    if typ is int:
        return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= limit else None
    if typ is str:
        return value[:limit] if isinstance(value, str) else None
    return None


def clean_client_event(raw):
    """A browser event reduced to the known type and props (strings cut short), or None."""
    if not isinstance(raw, dict) or not isinstance(raw.get("type"), str) or raw["type"] not in CLIENT_EVENTS:
        return None
    spec, props = CLIENT_EVENTS[raw["type"]], raw.get("props")
    props = props if isinstance(props, dict) else {}
    clean = {}
    for name, kind in spec.items():
        value = _clean_value(kind, props.get(name))
        if value is not None:
            clean[name] = value
    ts = raw.get("ts")
    return {"type": raw["type"], "props": clean,
            "client_ts": ts if isinstance(ts, int) and not isinstance(ts, bool) and 0 <= ts < 2 ** 53 else None}


def _referrer_host():
    try:
        return urlsplit(request.referrer or "").hostname
    except ValueError:  # a malformed Referer header
        return None


def init_analytics(app):
    app.permanent_session_lifetime = dt.timedelta(days=config.SESSION_DAYS)
    # Only a modified session sends the cookie (tracked pages modify it, so the 60 days slide with each page);
    # otherwise a permanent session would send it on every response, cached public ones included.
    app.config["SESSION_REFRESH_EACH_REQUEST"] = False

    @app.before_request
    def start_page_load():
        g.rid = None
        eventlog.current_rid.set(None)  # threads are reused: never inherit another request's page load
        if request.endpoint not in PAGE_ENDPOINTS or request.method not in ("GET", "POST"):
            return  # only pages (never publicly cached) may change the cookie
        if opted_out() and "aid" in session:  # turned on Global Privacy Control / Do Not Track since
            session.pop("aid", None)
            session.pop("aid_t", None)
        if tracking():
            _ensure_visitor()
            g.rid, g.an_t0 = secrets.token_urlsafe(8), time.monotonic()
            eventlog.current_rid.set(g.rid)

    @app.after_request
    def log_page_view(resp):
        try:
            if g.get("rid") and resp.status_code == 200 and resp.mimetype == "text/html":
                ref = _referrer_host()
                props = {"server_ms": int((time.monotonic() - g.an_t0) * 1000)}
                if ref and ref != request.host.split(":")[0]:
                    props["ref"] = ref[:100]
                for name in ("src", "utm_source", "utm_medium", "utm_campaign"):
                    if request.args.get(name):
                        props[name] = request.args[name][:64]
                measure = (request.view_args or {}).get("measure_id") or (
                    request.args.get("measure") if request.endpoint == "ask_page" else None)
                if measure:
                    props["measure"] = measure[:40]
                if g.get("an_zip"):
                    props["zip"] = g.an_zip
                log("pageview", props)
        except Exception:  # noqa: BLE001 - analytics never breaks a page
            pass
        return resp

    @app.context_processor
    def analytics_globals():
        token = None
        if g.get("rid") and session.get("aid"):
            token = sign_token(g.rid, session["aid"], int(time.time()))
        return {"analytics_token": token}

    @app.post("/api/e")
    def api_events():
        if (request.content_length or 0) > MAX_BODY:
            return jsonify(error="too large"), 400
        body = request.get_json(silent=True)
        events = body.get("events") if isinstance(body, dict) else None
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            return jsonify(error="bad batch"), 400
        if not tracking():
            return "", 204
        rid = verify_token(body.get("t"), session.get("aid"), int(time.time()))
        if not rid:
            return "", 204
        if not ratelimit.allow("events", "t:" + rid, [(BATCHES_PER_PAGE, TOKEN_SECONDS)]):
            return "", 204
        if not ratelimit.allow("events", ratelimit.client_key(request.remote_addr), [(BATCHES_PER_NETWORK_HOUR, 3600)]):
            return "", 204
        page = body.get("p") if isinstance(body.get("p"), str) and body["p"].startswith("/") else None
        for raw in events:
            try:
                ev = clean_client_event(raw)
                if ev:
                    line = _event(ev["type"], ev["props"], rid, path=(page or "")[:200] or None)
                    line["client_ts"] = ev["client_ts"]
                    eventlog.log_event(line)
            except Exception:  # noqa: BLE001 - one bad event never stops the batch
                continue
        return "", 204
