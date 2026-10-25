"""geo service: address -> likely districts, using only the ZIP code and a static table.

The address itself is never stored or logged; only the 5-digit ZIP is used.
"""

import json
import re

from flask import abort, jsonify, request

from ... import config
from ...servicekit import make_service

ZIP_RE = re.compile(r"\b(9[0-6]\d{3})(?:-\d{4})?\b")  # California ZIPs run 90001-96162


def extract_zip(address):
    """The last California-looking ZIP in the address, or None."""
    matches = ZIP_RE.findall(address or "")
    return matches[-1] if matches else None


def create_app(table_path=None):
    app = make_service("geo")
    with open(table_path or config.ZIP_TABLE_PATH) as fh:
        table = json.load(fh)["zips"]

    @app.post("/lookup")
    def lookup():
        body = request.get_json(silent=True) or {}
        address = body.get("address")
        if not isinstance(address, str) or not address.strip():
            abort(400, "address is required")
        zip_code = extract_zip(address)
        row = table.get(zip_code) if zip_code else None
        return jsonify(
            zip=zip_code,
            found=row is not None,
            basis="zip",
            city=row and row["city"],
            county=row and row["county"],
            districts=row and {k: row[k] for k in ("congressional", "state_senate", "assembly")},
        )

    return app
