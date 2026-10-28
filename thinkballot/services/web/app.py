"""web service: the pages voters see. It reads data only through the other services' APIs."""

import re
import secrets
import time

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for

from ... import config, ratelimit
from ...servicekit import ServiceClient, ServiceError
from ...suggested import SUGGESTED_QUESTIONS

SAMPLE_ADDRESS = "Mango Park, Sunnyvale, 94087"
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


CSP = ("default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; form-action 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; object-src 'none'")


def create_app():
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SECURE=config.PUBLIC_BASE.startswith("https://"),
                      MAX_CONTENT_LENGTH=64 * 1024)  # no uploads; forms and questions are small

    @app.after_request
    def security_headers(resp):
        # CSP and anti-framing belong to the app (the shared proxy sets HSTS, nosniff, Referrer-Policy).
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("X-Frame-Options", "DENY")
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

    COMMUNITY_ENDPOINTS = {"signin", "signout", "post_comment", "submit_fact", "flag_comment", "rate_fact",
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
        # Every HTML form carries a per-session token; JSON calls are same-origin by browser rules.
        if request.method == "POST" and not request.is_json:
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

    @app.context_processor
    def globals_():
        return {"base_url": config.PUBLIC_BASE, "headings": FIELD_HEADINGS,
                "suggested_questions": SUGGESTED_QUESTIONS, "user": current_user(), "csrf_token": csrf_token,
                "community_open": config.COMMUNITY_OPEN}

    def load_ballot():
        try:
            election, listing = ballot.get("/election"), ballot.get("/measures", level="state")
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
                               sample_address=SAMPLE_ADDRESS)

    @app.route("/ballot", methods=["GET", "POST"])
    def ballot_page():
        election, measures = load_ballot()
        place = None
        if request.method == "POST":  # address arrives in the form body, never in the URL
            address = request.form.get("address", "").strip()
            if address:
                try:
                    place = geo.post("/lookup", {"address": address})
                except ServiceError:
                    place = {"found": False, "zip": None, "error": True}
        local = None
        if place and place.get("found"):
            try:
                rows = ballot.get("/measures", level="local", county=place["county"])["measures"]
            except ServiceError:
                rows = []
            if rows:
                city = f"City of {place['city']}".lower()
                yours = [m for m in rows if m["district"].lower() == city
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
            election, measure = ballot.get("/election"), ballot.get(f"/measures/{measure_id}")
        except ServiceError:
            abort(503)
        if not measure:
            abort(404)
        # Number each distinct source page once, for the [1] [2] chips and the sources list.
        sources = []
        ordered = [measure["fields"][n] for n in FIELD_HEADINGS if n in measure["fields"]]
        for f in ordered:  # in the order they appear on the page
            if f["source_url"] not in [s["url"] for s in sources]:
                sources.append({"url": f["source_url"], "label": f["source_label"]})
        chip = {s["url"]: i + 1 for i, s in enumerate(sources)}
        u = current_user()
        try:
            zone = community.get(f"/measures/{measure_id}", viewer=u["id"] if u else None)
        except ServiceError:
            zone = None  # the official card still works if the community service is down
        results = load_results() if measure["level"] == "state" else None
        return render_template("measure.html", election=election, m=measure, sources=sources, chip=chip,
                               zone=zone, results=results)

    @app.post("/api/ask")
    def api_ask():
        body = request.get_json(silent=True) or {}
        if not isinstance(body.get("measure_id"), str) or not MEASURE_ID_RE.match(body["measure_id"]):
            return jsonify(status="error", reason="Unknown proposition."), 400
        payload = {"measure_id": body.get("measure_id"), "question": body.get("question"),
                   "client": request.remote_addr}
        try:
            result = ask_svc.post("/ask", payload)
        except ServiceError as exc:
            messages = {429: "Too many questions in a minute. Please wait a moment.",
                        400: "Please type a question."}
            return jsonify(status="error",
                           reason=messages.get(exc.status, "The question service is busy. Please try again.")), \
                exc.status if exc.status in messages else 503
        return jsonify(result)

    @app.get("/search")
    def search_page():
        try:
            result = search_svc.get("/search", q=request.args.get("q", ""), topic=request.args.get("topic", ""))
        except ServiceError:
            abort(503)
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
            if not ratelimit.allow("signin-" + str(action), client, limits):
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
            return None, redirect(url_for("measure_page", measure_id=measure_id) + "#community")
        try:
            result = community.post(path, payload)
            if ok_message:
                flash(ok_message)
        except ServiceError as exc:
            if exc.status == 401:  # the account behind this sign-in no longer exists
                session.clear()
            flash(exc.detail if exc.status < 500 else "The community service is unavailable right now.")
            result = None
        return result, redirect(url_for("measure_page", measure_id=measure_id) + "#community")

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
        return render_template("error.html", title="Page not found",
                               message="We couldn't find that page."), 404

    @app.errorhandler(503)
    def unavailable(_exc):
        return render_template("error.html", title="Temporarily unavailable",
                               message="Ballot data is unavailable right now. Please try again shortly."), 503

    return app
