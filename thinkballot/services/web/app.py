"""web service: the pages voters see. It reads data only through the other services' APIs."""

from flask import Flask, abort, jsonify, render_template, request

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
}


# Starter questions shown as buttons next to every Ask box. Checked by Bias Buster in the seed script.
SUGGESTED_QUESTIONS = [
    "What would change if this passes?",
    "What does it cost the state?",
    "What do supporters and opponents say?",
]


def create_app():
    app = Flask(__name__)
    ballot = ServiceClient("ballot")
    geo = ServiceClient("geo")
    ask_svc = ServiceClient("ask")
    bias = ServiceClient("bias")
    search_svc = ServiceClient("search")

    @app.context_processor
    def globals_():
        return {"base_url": config.PUBLIC_BASE, "headings": FIELD_HEADINGS,
                "suggested_questions": SUGGESTED_QUESTIONS}

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
        for f in measure["fields"].values():
            if f["source_url"] not in [s["url"] for s in sources]:
                sources.append({"url": f["source_url"], "label": f["source_label"]})
        chip = {s["url"]: i + 1 for i, s in enumerate(sources)}
        return render_template("measure.html", election=election, m=measure, sources=sources, chip=chip)

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
