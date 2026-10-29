"""web service: the pages voters see. It reads data only through the other services' APIs."""

import datetime as dt
import re
import secrets
import time
from zoneinfo import ZoneInfo

from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from ... import config, ratelimit
from ...servicekit import ServiceClient, ServiceError
from ...suggested import SUGGESTED_QUESTIONS
from . import i18n

SAMPLE_ZIP = "94087"
MEASURE_ID_RE = re.compile(r"^(prop|local)-[a-z0-9-]{1,24}$")
SAFE_NEXT_RE = re.compile(r"^/(?![/\\])[A-Za-z0-9._~!$&'()*+,;=:@%/?-]*$")  # same-site path, no //host

# Card field headings, in display order. YES and NO always use the same layout.
FIELD_HEADINGS = {
    "measure_type": "Measure type",
    "summary": "Official summary",
    "yes_means": "What a YES vote means",
    "no_means": "What a NO vote means",
    "fiscal_effect": "Fiscal effect",
    "argument_for": "Official argument in favor",
    "argument_against": "Official argument against",
    "supporters": "Supporters",
    "opponents": "Opponents",
    "analysis": "Analysis by the Legislative Analyst",
    "district": "Jurisdiction",
    "ballot_question": "The question on your ballot",
}


PACIFIC = ZoneInfo("America/Los_Angeles")
SPANISH_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
                  "noviembre", "diciembre"]

# Strings the browser code shows (static/app.js), handed to it in the page's language.
JS_STRINGS = {
    "star": "☆ Star", "starred": "★ Starred", "copy": "Copy this link:",
    "pass": "Bias Buster: passed", "revised": "Bias Buster: edited", "held": "Bias Buster: held back",
    "bias": "Bias Buster", "change": "1 change", "changes": "{n} changes",
    "prepared": "Prepared in advance from the official text on {day}.",
    "prepared_checked": "Prepared in advance from the official text on {day} and re-checked by Bias Buster just now.",
    "working": "Reading the official text, writing an answer, then Bias Buster checks it. This usually takes 30 to "
               "60 seconds.",
    "translated": "Translated by ThinkBallot from the English answer and checked. Quotes are official text.",
    "in_english": "This answer is in English.",
    "working_label": "Processing your question", "processing": "Processing…", "seconds": "s",
    "too_long": "That took too long. Please try again.",
    "offline": "Couldn't reach ThinkBallot. Check your connection.",
    "zip_unknown": "Please choose a California ZIP code from the list.",
}


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; form-action 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; object-src 'none'")


def create_app():
    app = Flask(__name__)
    app.wsgi_app = i18n.LanguagePrefix(app.wsgi_app)  # /es/... and /zh/... serve the same views
    app.secret_key = config.SECRET_KEY
    app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SECURE=config.PUBLIC_BASE.startswith("https://"),
                      MAX_CONTENT_LENGTH=64 * 1024)  # no uploads; forms and questions are small

    @app.after_request
    def security_headers(resp):
        # CSP and anti-framing belong to the app (the shared proxy sets HSTS, nosniff, Referrer-Policy).
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("X-Frame-Options", "DENY")
        if not config.IS_PRODUCTION:  # test copies stay out of search results
            resp.headers.setdefault("X-Robots-Tag", "noindex")
        return resp
    ballot = ServiceClient("ballot")
    geo = ServiceClient("geo")
    ask_svc = ServiceClient("ask")
    bias = ServiceClient("bias")
    search_svc = ServiceClient("search")
    community = ServiceClient("community")
    results_svc = ServiceClient("results")

    # ---------- sign-in state and form protection ----------
    def current_user():
        if not config.COMMUNITY_OPEN:
            return None
        return session.get("user")  # {"id", "username", "is_mod"} or None

    COMMUNITY_ENDPOINTS = {"signin", "signout", "verify", "post_comment", "submit_fact", "flag_comment", "rate_fact",
                           "moderation"}

    @app.before_request
    def community_closed():
        # While the community is closed, every account and posting route is off.
        if not config.COMMUNITY_OPEN and request.endpoint in COMMUNITY_ENDPOINTS:
            if request.endpoint == "signin" and request.method == "GET":
                return render_template("community_closed.html")
            abort(404)

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return session["csrf"]

    @app.before_request
    def check_csrf():
        # Every HTML form carries a per-session token. JSON calls carry none: browsers send
        # Sec-Fetch-Site, and anything but same-origin (or no header: non-browser callers) is refused.
        if request.method == "POST" and request.is_json:
            if request.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin":
                abort(403)
        elif request.method == "POST":
            expected = session.get("csrf")
            sent = request.form.get("csrf", "").encode()
            if not expected or not secrets.compare_digest(sent, expected.encode()):
                abort(400)

    def require_user():
        u = current_user()
        if not u:
            flash("Please sign in first.")
            abort(redirect(url_for("signin", next=request.referrer or "/")))
        return u

    # ---------- language ----------
    @app.before_request
    def set_language():
        g.lang = request.environ.get("tb.lang", i18n.DEFAULT)

    @app.before_request
    def english_only_pages():
        # Accounts, verification and moderation are English only (closed until after the election):
        # their language-prefixed addresses go to the English page.
        if g.lang != i18n.DEFAULT and request.endpoint in COMMUNITY_ENDPOINTS | {"moderation"} \
                and request.method == "GET":
            return redirect(request.full_path.rstrip("?"))

    def lang():
        return getattr(g, "lang", i18n.DEFAULT)

    def api_lang():  # what the ballot service is asked for: None means English
        return None if lang() == i18n.DEFAULT else lang()

    def _(text, **values):
        return i18n.gettext(lang(), text, **values)

    def lp(path):
        """A site path in the current page's language."""
        return i18n.lang_path(lang(), path)

    def T(text, **values):
        """Plain text (values filled in, nothing escaped): for attributes, which Jinja escapes once, and
        for flash messages and JSON."""
        return _(text, **values).unescape()

    def _d(text):
        """A data label (election name, topic) in the page's language; always escaped."""
        return i18n.data_label(lang(), text)

    # Also as Jinja globals, so macros imported without the page context (e.g. _results.html) have them.
    app.jinja_env.globals.update({"_": _, "_a": T, "_d": _d, "lp": lp, "page_lang": lang})

    @app.template_filter("results_time")
    def results_time(res):
        """When results were last updated, in the page's language (English: the results service's own text)."""
        if lang() == i18n.DEFAULT or not res.get("as_of"):
            return res.get("as_of_text", "")
        p = dt.datetime.fromisoformat(res["as_of"]).astimezone(PACIFIC)
        hour = p.hour % 12 or 12
        if lang() == "es":
            return f"{p.day} de {SPANISH_MONTHS[p.month - 1]} de {p.year}, {hour}:{p:%M} {'a. m.' if p.hour < 12 else 'p. m.'} PT"
        return f"{p.year}年{p.month}月{p.day}日{'上午' if p.hour < 12 else '下午'} {hour}:{p:%M}（太平洋時間）"

    @app.context_processor
    def globals_():
        here = request.path  # without the language prefix
        query = request.query_string.decode("latin-1")
        return {"base_url": config.PUBLIC_BASE, "canonical_base": config.CANONICAL_BASE,
                "is_production": config.IS_PRODUCTION, "headings": FIELD_HEADINGS,
                "suggested_questions": SUGGESTED_QUESTIONS, "user": current_user(), "csrf_token": csrf_token,
                "community_open": config.COMMUNITY_OPEN,
                "lang": lang(), "html_lang": i18n.LANGS[lang()]["html"], "og_locale": i18n.LANGS[lang()]["og"],
                "_": _, "_a": T, "_d": _d,  # _a: plain text for attributes; _d: data labels
                "lp": lp, "lang_prefix": "" if lang() == i18n.DEFAULT else "/" + lang(),
                "languages": [{"code": code, "name": info["name"], "short": info["short"], "html": info["html"],
                               "hreflang": info["hreflang"], "current": code == lang(),
                               "path": i18n.lang_path(code, here),
                               "href": i18n.lang_path(code, here) + ("?" + query if query else "")}
                              for code, info in i18n.LANGS.items()],
                "js_strings": {k: T(v) for k, v in JS_STRINGS.items()}}

    def load_ballot():
        try:
            election, listing = ballot.get("/election"), ballot.get("/measures", level="state", lang=api_lang())
        except ServiceError:
            abort(503)
        if not election:  # no data loaded yet
            abort(503)
        return election, listing["measures"]

    def load_results():
        """Official results, or None (before election night, or if the results service is down)."""
        try:
            res = results_svc.get("/results")
        except ServiceError:
            return None
        return res if res and res.get("available") else None

    @app.get("/api/health")
    def health():
        """Proves the web service AND the ballot service and its data are serving."""
        try:
            election = ballot.get("/election")
        except ServiceError:
            election = None
        if not election:
            return jsonify(status="degraded"), 503
        return jsonify(status="ok")

    @app.get("/")
    def landing():
        election, measures = load_ballot()
        return render_template("landing.html", election=election, count=len(measures),
                               sample_zip=SAMPLE_ZIP)

    @app.route("/ballot", methods=["GET", "POST"])
    def ballot_page():
        election, measures = load_ballot()
        place = None
        if request.method == "POST":  # the ZIP code arrives in the form body, never in the URL
            zip_code = request.form.get("zip", "").strip()
            if zip_code:
                try:
                    place = geo.post("/lookup", {"address": zip_code})
                except ServiceError:
                    place = {"found": False, "zip": None, "error": True}
        local = None
        if place and place.get("found"):
            try:
                rows = ballot.get("/measures", level="local", county=place["county"], lang=api_lang())["measures"]
            except ServiceError:
                rows = []
            if rows:
                places = {f"{kind} of {place['city']}".lower() for kind in ("City", "Town")}
                yours = [m for m in rows if m["district"].lower() in places
                         or "county" in m["district"].lower() or "transit" in m["district"].lower()]
                local = {"county": place["county"], "yours": yours,
                         "maybe": [m for m in rows if m not in yours]}
        return render_template("ballot.html", election=election, measures=measures, place=place, local=local,
                               results=load_results())

    @app.url_value_preprocessor
    def check_measure_id(_endpoint, values):
        # Measure ids end up in service URLs; allow only the real shape ("prop-45").
        if values and "measure_id" in values and not MEASURE_ID_RE.match(values["measure_id"]):
            abort(404)

    @app.get("/prop/<measure_id>")
    def measure_page(measure_id):
        try:
            election, measure = ballot.get("/election"), ballot.get(f"/measures/{measure_id}", lang=api_lang())
        except ServiceError:
            abort(503)
        if not measure:
            abort(404)
        # Number each distinct source page once, for the [1] [2] chips and the sources list.
        sources = []
        ordered = [measure["fields"][n] for n in FIELD_HEADINGS if n in measure["fields"]]
        for f in ordered:  # in the order they appear on the page
            if f["source_url"] not in [s["url"] for s in sources]:
                sources.append({"url": f["source_url"], "label": f["source_label"], "lang": f.get("lang")})
        chip = {s["url"]: i + 1 for i, s in enumerate(sources)}
        u = current_user()
        try:
            zone = community.get(f"/measures/{measure_id}", viewer=u["id"] if u else None)
        except ServiceError:
            zone = None  # the official card still works if the community service is down
        results = load_results() if measure["level"] == "state" else None
        return render_template("measure.html", election=election, m=measure, sources=sources, chip=chip,
                               zone=zone, results=results)

    @app.get("/robots.txt")
    def robots():
        if config.IS_PRODUCTION:
            body = f"User-agent: *\nDisallow: /api/\nSitemap: {config.CANONICAL_BASE}/sitemap.xml\n"
        else:
            body = "User-agent: *\nDisallow: /\n"
        return app.response_class(body, mimetype="text/plain")

    sitemap_body = []

    @app.get("/sitemap.xml")
    def sitemap():
        """Every public page in every language, with its translations listed (production only)."""
        if not config.IS_PRODUCTION:
            abort(404)
        if sitemap_body:  # built once per process: the measures only change with a release
            return app.response_class(sitemap_body[0], mimetype="application/xml")
        try:
            ids = [m["id"] for m in ballot.get("/measures")["measures"]]
        except ServiceError:
            abort(503)
        paths = ["/", "/ballot", "/search", "/ask", "/neutral", "/about"] + [f"/prop/{i}" for i in ids]
        xml = render_template("sitemap.xml", paths=paths, base=config.CANONICAL_BASE,
                              langs=[(code, info["hreflang"]) for code, info in i18n.LANGS.items()],
                              lang_path=i18n.lang_path)
        sitemap_body.append(xml)
        return app.response_class(xml, mimetype="application/xml")

    @app.get("/api/zips")
    def api_zips():
        try:
            result = geo.get("/zips")
        except ServiceError:
            abort(503)
        resp = jsonify(result)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    @app.post("/api/ask")
    def api_ask():
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("measure_id"), str) or not MEASURE_ID_RE.match(body["measure_id"]):
            return jsonify(status="error", reason=T("Unknown proposition.")), 400
        # The page's language comes from the address (/es/api/ask); a suggested-question button sends
        # its number, so the prepared answer is found whatever language the button shows.
        suggested = body.get("suggested") if type(body.get("suggested")) is int else None
        payload = {"measure_id": body.get("measure_id"), "question": body.get("question"),
                   "client": request.remote_addr}
        if suggested is not None:
            payload.update(suggested=suggested, lang=api_lang())
        try:
            result = ask_svc.post("/ask", payload)
        except ServiceError as exc:
            if exc.status == 429:
                site = exc.detail == "site_limit"  # the site-wide cap, not this visitor's own limit
                reason = (T("ThinkBallot is answering a lot of questions right now. Please try again later.") if site
                          else T("Too many questions in a minute. Please wait a moment."))
                return jsonify(status="error", reason=reason), 429
            if exc.status == 400:
                return jsonify(status="error", reason=T("Please type a question.")), 400
            return jsonify(status="error", reason=T("The question service is busy. Please try again.")), 503
        if suggested is not None and result.get("status") == "refused":
            result["reason"] = T(result["reason"])  # a fixed reply: its catalog translation (no AI)
        if result.get("translated"):  # an English quote's source, named in the page's language
            for p in result.get("points", []):
                if p.get("quote_lang") == "en" and p.get("source_field") in FIELD_HEADINGS:
                    p["source_label"] = _d(FIELD_HEADINGS[p["source_field"]]).unescape()
        return jsonify(result)

    @app.get("/search")
    def search_page():
        try:
            result = search_svc.get("/search", q=request.args.get("q", ""), topic=request.args.get("topic", ""))
        except ServiceError:
            abort(503)
        if api_lang() and result.get("results"):  # official translated titles where there are some
            try:
                titles = {m["id"]: m["title"] for m in ballot.get("/measures", lang=api_lang())["measures"]
                          if "title" in m.get("translated", [])}
            except ServiceError:
                titles = {}
            for m in result["results"]:
                if m["id"] in titles:
                    m["title"], m["title_lang"] = titles[m["id"]], api_lang()
        return render_template("search.html", r=result)

    @app.get("/ask")
    def ask_page():
        election, measures = load_ballot()
        chosen = request.args.get("measure") or (measures[0]["id"] if measures else None)
        return render_template("ask.html", election=election, measures=measures, chosen=chosen)

    # ---------- accounts ----------
    CHECK_EMAIL = ("Almost done: we've emailed you a link and a passcode. Open the link and enter the passcode "
                   "within 30 minutes to finish creating your account. Nothing there? Sign in to get a new email.")

    def pending_account():
        """The unverified account whose password was just entered here, if still recent."""
        p = session.get("verify_pending")
        if p and p.get("until", 0) > time.time():
            return p
        session.pop("verify_pending", None)
        return None

    @app.route("/signin", methods=["GET", "POST"])
    def signin():
        next_url = request.values.get("next") or "/"
        if not SAFE_NEXT_RE.fullmatch(next_url):
            next_url = "/"  # only redirect to a path on this site
        if request.method == "POST":
            form = request.form
            action = form.get("action")
            client = ratelimit.client_key(request.remote_addr)
            limits = {"signup": [(5, 3600)], "resend": [(3, 3600)]}.get(action, [(10, 600)])
            # Sign-in attempts are also limited per email, so many addresses can't guess one password.
            email = (form.get("email") or "").strip().lower()[:254]
            if not (ratelimit.allow("signin-" + str(action), client, limits)
                    and (action in ("signup", "resend") or ratelimit.allow("signin-email", email, [(10, 900)]))):
                flash("Too many attempts. Please wait a few minutes and try again."
                      if action != "resend" else "Too many emails. Please wait an hour and try again.")
                return redirect(url_for("signin", next=next_url))
            try:
                if action == "resend":
                    pending = pending_account()
                    if pending:
                        community.post("/users/resend", {"user_id": pending["id"]})
                        flash("We've sent a new email with a link and a passcode. It works for 30 minutes.")
                    else:
                        flash("Please sign in again to get a new email.")
                    return redirect(url_for("signin", next=next_url))
                if action == "signup":
                    community.post("/users", {"email": form.get("email"), "username": form.get("username"),
                                              "password": form.get("password")})
                    flash(CHECK_EMAIL)  # the same whether or not the email already had an account
                    return redirect(url_for("signin", next=next_url))
                u = community.post("/login", {"email": form.get("email"), "password": form.get("password")})
            except ServiceError as exc:
                if exc.status == 503 and action in ("signup", "resend"):
                    flash(exc.detail)
                else:
                    flash(exc.detail if exc.status < 500 else "Sign-in is unavailable right now.")
                return redirect(url_for("signin", next=next_url))
            session.clear()
            if u.get("verified") is not True:
                session["verify_pending"] = {"id": u["id"], "until": time.time() + 1800}
                flash("Please confirm your email before signing in. Use the link and passcode we emailed you, "
                      "or get a new email below.")
                return redirect(url_for("signin", next=next_url))
            session["user"] = {"id": u["id"], "username": u["username"], "is_mod": u["is_mod"]}
            return redirect(next_url)
        return render_template("signin.html", next=next_url, pending=pending_account())

    @app.route("/verify", methods=["GET", "POST"])
    def verify():
        token = request.values.get("t", "")
        if request.method == "POST":
            client = ratelimit.client_key(request.remote_addr)
            if not ratelimit.allow("verify", client, [(20, 3600)]):
                flash("Too many attempts. Please wait a few minutes and try again.")
                return verify_page(token, valid=True)
            try:
                u = community.post("/verify", {"token": token, "code": request.form.get("code", "")})
            except ServiceError as exc:
                if exc.status >= 500:
                    flash("Verification is unavailable right now. Please try again shortly.")
                    return verify_page(token, valid=True)
                flash(exc.detail)
                return verify_page(token, valid=exc.status != 410)
            session.clear()
            session["user"] = {"id": u["id"], "username": u["username"], "is_mod": u["is_mod"]}
            flash("Your email is confirmed and you're signed in. Welcome!")
            return redirect("/")
        try:
            valid = bool(token) and community.post("/verify/check", {"token": token})["valid"]
        except ServiceError:
            valid = True  # let them try; the passcode step checks the link again
        return verify_page(token, valid)

    def verify_page(token, valid):
        resp = app.make_response(render_template("verify.html", token=token if valid else "", valid=valid))
        # The link's token is in this page's URL: keep it out of Referer headers and caches.
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/signout")
    def signout():
        session.clear()
        return redirect("/")

    # ---------- community ----------
    def community_action(path, payload, measure_id, ok_message=None):
        if not ratelimit.allow("community", f"user:{payload['user_id']}", [(10, 60), (100, 86400)]):
            flash("You're posting very quickly. Please wait a minute.")
            return None, redirect(lp(url_for("measure_page", measure_id=measure_id)) + "#community")
        try:
            result = community.post(path, payload)
            if ok_message:
                flash(ok_message)
        except ServiceError as exc:
            if exc.status == 401:  # the account behind this sign-in no longer exists
                session.clear()
            flash(exc.detail if exc.status < 500 else "The community service is unavailable right now.")
            result = None
        return result, redirect(lp(url_for("measure_page", measure_id=measure_id)) + "#community")

    @app.post("/prop/<measure_id>/comment")
    def post_comment(measure_id):
        u = require_user()
        return community_action("/comments", {"user_id": u["id"], "measure_id": measure_id,
                                              "text": request.form.get("text")}, measure_id)[1]

    @app.post("/prop/<measure_id>/fact")
    def submit_fact(measure_id):
        u = require_user()
        return community_action("/facts", {"user_id": u["id"], "measure_id": measure_id,
                                           "text": request.form.get("text"),
                                           "citation_url": request.form.get("citation_url")},
                                measure_id, "Thanks! Your fact is pending until people who lean both ways rate it "
                                            "helpful, and a moderator reviews it.")[1]

    @app.post("/prop/<measure_id>/comment/<int:comment_id>/flag")
    def flag_comment(measure_id, comment_id):
        u = require_user()
        return community_action(f"/comments/{comment_id}/flag", {"user_id": u["id"]}, measure_id,
                                "Thanks. A moderator will take a look.")[1]

    @app.post("/prop/<measure_id>/fact/<int:fact_id>/rate")
    def rate_fact(measure_id, fact_id):
        u = require_user()
        payload = {"user_id": u["id"], "helpful": request.form.get("helpful") == "1",
                   "leaning": request.form.get("leaning")}
        return community_action(f"/facts/{fact_id}/rate", payload, measure_id, "Thanks for rating.")[1]

    @app.route("/moderation", methods=["GET", "POST"])
    def moderation():
        u = current_user()
        if not u or not u.get("is_mod"):
            abort(404)
        if request.method == "POST":
            kind, item, action = request.form.get("kind"), request.form.get("id"), request.form.get("action")
            if kind in ("comments", "facts") and (item or "").isdigit():
                try:
                    community.post(f"/moderation/{kind}/{item}", {"user_id": u["id"], "action": action})
                except ServiceError as exc:
                    flash(exc.detail)
            return redirect(url_for("moderation"))
        try:
            q = community.get("/moderation", user_id=u["id"])
        except ServiceError:
            abort(503)
        return render_template("moderation.html", q=q)

    @app.get("/neutral")
    def neutral():
        try:
            report = bias.get("/report")
        except ServiceError:
            report = None  # the page still explains the rules without the latest numbers
        return render_template("neutral.html", report=report)

    @app.get("/about")
    def about():
        return render_template("about.html")

    @app.errorhandler(404)
    def not_found(_exc):
        return render_template("error.html", title=_("Page not found"),
                               message=_("We couldn't find that page.")), 404

    @app.errorhandler(503)
    def unavailable(_exc):
        return render_template("error.html", title=_("Temporarily unavailable"),
                               message=_("Ballot data is unavailable right now. Please try again shortly.")), 503

    return app
