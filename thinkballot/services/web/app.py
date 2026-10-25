"""web service: the pages voters see. It reads data only through the other services' APIs."""

import secrets

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for

from ... import config
from ...servicekit import ServiceClient, ServiceError

SAMPLE_ADDRESS = "Mango Park, Sunnyvale, 94087"

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
}


# Starter questions shown as buttons next to every Ask box. Checked by Bias Buster in the seed script.
SUGGESTED_QUESTIONS = [
    "What would change if this passes?",
    "What does it cost the state?",
    "What do supporters and opponents say?",
]


def create_app():
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SECURE=config.PUBLIC_BASE.startswith("https://"))
    ballot = ServiceClient("ballot")
    geo = ServiceClient("geo")
    ask_svc = ServiceClient("ask")
    bias = ServiceClient("bias")
    search_svc = ServiceClient("search")
    community = ServiceClient("community")

    # ---------- sign-in state and form protection ----------
    def current_user():
        return session.get("user")  # {"id", "username", "is_mod"} or None

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(24)
        return session["csrf"]

    @app.before_request
    def check_csrf():
        # Every HTML form carries a per-session token; JSON calls are same-origin by browser rules.
        if request.method == "POST" and not request.is_json:
            if request.form.get("csrf") != session.get("csrf"):
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
                "suggested_questions": SUGGESTED_QUESTIONS, "user": current_user(), "csrf_token": csrf_token}

    def load_ballot():
        try:
            election, listing = ballot.get("/election"), ballot.get("/measures")
        except ServiceError:
            abort(503)
        if not election:  # no data loaded yet
            abort(503)
        return election, listing["measures"]

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
        return render_template("ballot.html", election=election, measures=measures, place=place)

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
        return render_template("measure.html", election=election, m=measure, sources=sources, chip=chip,
                               zone=zone)

    @app.post("/api/ask")
    def api_ask():
        body = request.get_json(silent=True) or {}
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
    @app.route("/signin", methods=["GET", "POST"])
    def signin():
        next_url = request.values.get("next") or "/"
        if not next_url.startswith("/") or next_url.startswith("//"):
            next_url = "/"  # only redirect within this site
        if request.method == "POST":
            form = request.form
            try:
                if form.get("action") == "signup":
                    u = community.post("/users", {"email": form.get("email"), "username": form.get("username"),
                                                  "password": form.get("password")})
                else:
                    u = community.post("/login", {"email": form.get("email"), "password": form.get("password")})
            except ServiceError as exc:
                flash(exc.detail if exc.status < 500 else "Sign-in is unavailable right now.")
                return redirect(url_for("signin", next=next_url))
            session.clear()
            session["user"] = {"id": u["id"], "username": u["username"], "is_mod": u["is_mod"]}
            return redirect(next_url)
        return render_template("signin.html", next=next_url)

    @app.post("/signout")
    def signout():
        session.clear()
        return redirect("/")

    # ---------- community ----------
    def community_action(path, payload, measure_id, ok_message=None):
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
