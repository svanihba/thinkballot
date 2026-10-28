"""Extraction: turn the raw store into ThinkBallot's data file. Never touches the network.

    python -m pipeline.extract.run       ->  data/extracted/<source>.json  and  data/measures.json

Each field records where it came from: page URL, the raw object (sha256) it was cut from, when it was
fetched, and whether the crawler or a supervised browser capture fetched it.
"""

import importlib
import json
import re
import subprocess
import sys

from ..rawstore import ROOT, RawStore, load_sources

ELECTION = {"id": "ca-2026-11-03", "name": "November 3, 2026 California General Election", "date": "2026-11-03"}
OUT_DIR = ROOT / "data" / "extracted"


def is_pdf(page):
    return "pdf" in (page["content_type"] or "") or page["body"][:5] == b"%PDF-"


def pdf_text(body):
    """Text of a PDF in reading order (poppler's pdftotext -raw), one line per line, single spaces.

    -raw keeps every printed character: the default mode drops hyphens at line ends, which turns
    official words like "non-payment" into "nonpayment". A line ending in "letter-" is joined to the
    next line with no space, so a hyphenated word stays whole and keeps its hyphen."""
    out = subprocess.run(["pdftotext", "-raw", "-enc", "UTF-8", "-", "-"], input=body, capture_output=True,
                         check=True)
    lines = [" ".join(line.split()) for line in out.stdout.decode("utf-8").split("\n")]
    joined = []
    for line in (line for line in lines if line):
        if joined and re.search(r"[A-Za-z]-$", joined[-1]) and line[:1].isalpha():
            joined[-1] += line
        else:
            joined.append(line)
    return "\n".join(joined)


def main(argv):
    store = RawStore()
    sources = load_sources()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_measures, failures = [], 0
    for sid in argv or list(sources):
        src = sources[sid]
        rows = store.latest_pages(sid)
        if not rows:
            print(f"{sid}: nothing in the raw store yet - skipped")
            continue
        pages = {url: dict(row, body=store.read(row["sha256"])) for url, row in rows.items()}
        for page in pages.values():  # PDFs: extract and verify against one saved text version
            if is_pdf(page):
                page["text"] = pdf_text(page["body"])
                page["text_sha256"] = store.put(page["text"].encode("utf-8"))

        def field(text, url, label, _pages=pages):
            row = _pages[url]
            snapshot = row.get("text_sha256") or row["sha256"]
            entry = {"text": text, "source_url": url, "source_label": label,
                     "source_snapshot": str(store.object_path(snapshot).relative_to(ROOT)),
                     "raw_sha256": row["sha256"], "fetched_at": row["fetched_at"],
                     "fetched_by": row["run_kind"]}
            if row.get("text_sha256"):
                entry["snapshot_kind"] = "pdf-text"
            return entry

        module = importlib.import_module(f"pipeline.extract.{src['extractor']}")
        try:
            measures = module.extract(pages, field)
        except ValueError as exc:
            print(f"{sid}: EXTRACTION FAILED - {exc}")
            failures += 1
            continue
        (OUT_DIR / f"{sid}.json").write_text(json.dumps(measures, indent=2, ensure_ascii=False) + "\n")
        print(f"{sid}: {len(measures)} measures from {len(pages)} raw pages")
        all_measures += measures
    if failures:
        print("Not writing data/measures.json: an extractor failed.")
        return 1
    (ROOT / "data" / "measures.json").write_text(json.dumps(
        {"_note": "Built by pipeline/extract/run.py from the raw store (data/raw). Do not edit by hand.",
         "election": ELECTION, "measures": all_measures}, indent=2, ensure_ascii=False) + "\n")
    print(f"data/measures.json: {len(all_measures)} measures")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
