"""ballot service: read-only JSON API over the measures in SQLite."""

from flask import abort, g, jsonify, request

from ...servicekit import make_service
from . import db


def create_app(db_path=None):
    app = make_service("ballot")

    def conn():
        if "conn" not in g:
            g.conn = db.connect_readonly(db_path)
        return g.conn

    @app.teardown_appcontext
    def close(_exc):
        c = g.pop("conn", None)
        if c is not None:
            c.close()

    @app.get("/election")
    def election():
        e = db.election(conn())
        if not e:
            abort(404, "No election loaded. Run scripts/seed.py.")
        return jsonify(e)

    @app.get("/measures")
    def measures():
        """?level=state|local and ?county=Santa Clara filter the list; ?lang=es|zh gives official translations."""
        rows = db.list_measures(conn(), request.args.get("lang"))
        level, county = request.args.get("level"), request.args.get("county")
        rows = [m for m in rows if (not level or m["level"] == level) and (not county or m["county"] == county)]
        return jsonify(measures=rows)

    @app.get("/measures/<measure_id>")
    def measure(measure_id):
        m = db.get_measure(conn(), measure_id, request.args.get("lang"))
        if not m:
            abort(404, "Unknown measure.")
        return jsonify(m)

    return app
