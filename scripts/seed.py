"""Load proposition data into SQLite, but only after the Bias Buster Engine has checked it.

    python scripts/seed.py [data/measures.json]

1. verify:  every official field must appear word for word on its source page.
2. audit:   official fields are checked for numbers, loaded words and YES/NO balance; findings are
            recorded, the text is never changed.
3. enforce: every label ThinkBallot itself writes must pass all checks.
Nothing is loaded if step 1 or 3 fails. A report goes to reports/bias-report.json.
"""

import html
import json
import re
import sys
import threading
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from thinkballot import config  # noqa: E402
from thinkballot.servicekit import ServiceClient, ServiceError  # noqa: E402
from thinkballot.services.ask.app import FIELD_LABELS as ASK_LABELS  # noqa: E402
from thinkballot.services.ballot import db  # noqa: E402
from thinkballot.services.web.app import FIELD_HEADINGS, SUGGESTED_QUESTIONS  # noqa: E402

DEFAULT_DATA = config.ROOT / "data" / "dummy" / "measures.json"
REPORT_PATH = config.ROOT / "reports" / "bias-report.json"


class _TextExtractor(HTMLParser):
    """Visible text of an HTML page (skips scripts and styles)."""

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def page_text(entry, cache):
    """Text of the source page for a field: a saved snapshot if given, else the live page."""
    key = entry.get("source_snapshot") or entry["source_url"]
    if key not in cache:
        if entry.get("source_snapshot"):
            raw = (config.ROOT / entry["source_snapshot"]).read_text()
        else:
            resp = requests.get(entry["source_url"], timeout=30, headers={"User-Agent": "ThinkBallot seed"})
            resp.raise_for_status()
            raw = resp.text
        if "<" in raw and ">" in raw:
            parser = _TextExtractor()
            parser.feed(raw)
            raw = " ".join(parser.parts)
        cache[key] = re.sub(r"\s+", " ", html.unescape(raw))
    return cache[key]


def bias_client():
    """Use the running bias service; if none is running, start one just for this script."""
    client = ServiceClient("bias")
    try:
        client.get("/health")
        return client, None
    except ServiceError:
        from thinkballot.services.bias.app import create_app
        import logging
        logging.getLogger("werkzeug").setLevel(logging.WARNING)
        server = make_server("127.0.0.1", 0, create_app(), threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"(started a local bias service on port {server.server_port})")
        return ServiceClient("bias", f"http://127.0.0.1:{server.server_port}"), server


def main(path):
    data = json.loads(Path(path).read_text())
    bias, server = bias_client()
    cache, report = {}, {"verify": [], "audit": [], "labels": []}
    failures = 0

    for m in data["measures"]:
        entries = [("title", m["title"])] + list(m["fields"].items())
        for name, entry in entries:
            source = page_text(entry, cache)
            v = bias.post("/check/text", {"text": entry["text"], "sources": [source], "mode": "verify"})
            report["verify"].append({"measure": m["id"], "field": name, "verdict": v["verdict"]})
            if v["verdict"] != "pass":
                failures += 1
                print(f"VERIFY FAIL {m['id']}.{name}: not found word for word on {entry['source_url']}")
            if name == "title":
                continue
            sides = None
            if name == "yes_means":
                no = m["fields"].get("no_means", {}).get("text")
                sides = {"yes": entry["text"], "no": no}
            a = bias.post("/check/text", {"text": entry["text"], "sources": [source], "mode": "audit",
                                          "sides": sides})
            for f in a["findings"]:
                report["audit"].append({"measure": m["id"], "field": name, **f})

    topics = {t for m in data["measures"] for t in m.get("topics", [])}
    labels = sorted(set(FIELD_HEADINGS.values()) | set(ASK_LABELS.values()) | topics
                    | set(SUGGESTED_QUESTIONS))
    for label in labels:
        r = bias.post("/check/text", {"text": label, "sources": [], "mode": "enforce"})
        report["labels"].append({"label": label, "verdict": r["verdict"], "findings": r["findings"]})
        if r["verdict"] != "pass":
            failures += 1
            print(f"LABEL FAIL {label!r}: {r['findings']}")

    report["summary"] = {
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "data_file": str(Path(path).resolve().relative_to(config.ROOT)),
        "fields_verified": sum(1 for v in report["verify"] if v["verdict"] == "pass"),
        "fields_failed": sum(1 for v in report["verify"] if v["verdict"] != "pass"),
        "labels_checked": len(labels),
        "audit_findings": len(report["audit"]),
    }
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    if server:
        server.shutdown()

    if failures:
        print(f"Not loaded: {failures} check(s) failed. See {REPORT_PATH.relative_to(config.ROOT)}.")
        return 1
    db.replace_all(db.connect(), data["election"], data["measures"])
    print(f"Loaded {len(data['measures'])} measures. {report['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DATA))
