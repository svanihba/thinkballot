"""Load proposition data into SQLite, but only after the Bias Buster Engine has checked it.

    python scripts/seed.py [data/measures.json]

1. verify:  every official field must appear word for word on its source page.
2. audit:   official fields are checked for numbers, loaded words and YES/NO balance; findings are
            recorded, the text is never changed.
3. enforce: every label ThinkBallot itself writes must pass all checks.
Nothing is loaded if step 1 or 3 fails. A report goes to reports/bias-report.json.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from thinkballot import config  # noqa: E402
from thinkballot.servicekit import ServiceError  # noqa: E402
from thinkballot.sourcetext import html_to_text  # noqa: E402
from thinkballot.services.ask.app import FIELD_LABELS as ASK_LABELS  # noqa: E402
from thinkballot.services.ballot import db  # noqa: E402
from thinkballot.services.web.app import FIELD_HEADINGS, SUGGESTED_QUESTIONS  # noqa: E402

DEFAULT_DATA = config.ROOT / "data" / "measures.json"
REPORT_PATH = config.REPORT_PATH


def page_text(entry, cache, live=False):
    """Text of the source page for a field: the live page with --live, else the saved snapshot if any."""
    # Pages captured in a supervised browser session come from sites that block automated clients:
    # they are verified against that capture, never re-fetched by a script.
    # PDFs are verified against the text extracted from the saved PDF (the server has no PDF reader),
    # scanned PDFs against the saved OCR reading of the page.
    from_pdf = entry.get("snapshot_kind") in ("pdf-text", "pdf-ocr")
    captured = entry.get("fetched_by") == "capture" or from_pdf
    use_snapshot = entry.get("source_snapshot") and (captured or not (live and entry["source_url"].startswith("https://")))
    key = entry["source_snapshot"] if use_snapshot else entry["source_url"]
    if key not in cache:
        if use_snapshot:
            raw = (config.ROOT / entry["source_snapshot"]).read_text(encoding="utf-8")
        else:
            resp = requests.get(entry["source_url"], timeout=30, headers={"User-Agent": "ThinkBallot seed"})
            resp.raise_for_status()
            raw = resp.content.decode("utf-8")  # the guide is UTF-8; its headers don't say so
        is_html = "<" in raw and ">" in raw and not from_pdf
        cache[key] = html_to_text(raw) if is_html else raw
    return cache[key]


class _InProcessBias:
    """The bias service app called through WSGI in this process (same JSON API, no listener)."""

    def __init__(self):
        from thinkballot.services.bias.app import create_app
        self.client = create_app().test_client()
        self.headers = {"X-TB-Internal": config.INTERNAL_TOKEN}

    def get(self, path, **params):
        return self.client.get(path, query_string=params, headers=self.headers).get_json()

    def post(self, path, payload):
        resp = self.client.post(path, json=payload, headers=self.headers)
        if resp.status_code >= 400:
            raise ServiceError("bias", f"HTTP {resp.status_code}", resp.status_code)
        return resp.get_json()


def bias_client():
    """Always the bias service in-process: the seed never depends on (or talks to) any listener."""
    return _InProcessBias()


def main(path, live=False):
    data = json.loads(Path(path).read_text())
    bias = bias_client()
    cache, report = {}, {"verify": [], "audit": [], "labels": []}
    failures = 0

    for m in data["measures"]:
        entries = [("title", m["title"])] + list(m["fields"].items())
        for lang, tr in sorted(m.get("translations", {}).items()):  # official translations: verified the same way
            entries += [(f"{lang}:title", tr["title"])] + [(f"{lang}:{k}", v) for k, v in tr["fields"].items()]
        for name, entry in entries:
            source = page_text(entry, cache, live)
            v = bias.post("/check/text", {"text": entry["text"], "sources": [source], "mode": "verify"})
            report["verify"].append({"measure": m["id"], "field": name, "verdict": v["verdict"],
                                     "against": "browser capture" if entry.get("fetched_by") == "capture"
                                     else "saved PDF text" if entry.get("snapshot_kind") == "pdf-text"
                                     else "OCR of a scanned PDF" if entry.get("snapshot_kind") == "pdf-ocr"
                                     else ("live page" if live else "saved copy")})
            if v["verdict"] != "pass":
                failures += 1
                print(f"VERIFY FAIL {m['id']}.{name}: not found word for word on {entry['source_url']}")
            if name == "title" or ":" in name:  # the audit's word lists are English
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
        "verified_against": "live official pages" if live else "saved copies of the official pages",
        "fields_verified_against_browser_captures": sum(1 for v in report["verify"]
                                                        if v["against"] == "browser capture"),
        "fields_verified_against_ocr": sum(1 for v in report["verify"] if v["against"] == "OCR of a scanned PDF"),
        "fields_verified":sum(1 for v in report["verify"] if v["verdict"] == "pass"),
        "fields_failed": sum(1 for v in report["verify"] if v["verdict"] != "pass"),
        "labels_checked": len(labels),
        "audit_findings": len(report["audit"]),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")

    if failures:
        print(f"Not loaded: {failures} check(s) failed. See {REPORT_PATH}.")
        return 1
    db.replace_all(db.connect(), data["election"], data["measures"])
    print(f"Loaded {len(data['measures'])} measures. {report['summary']}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data", nargs="?", default=DEFAULT_DATA)
    parser.add_argument("--live", action="store_true", help="verify against the live official pages")
    args = parser.parse_args()
    sys.exit(main(args.data, args.live))
