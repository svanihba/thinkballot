"""Extraction: turn the raw store into ThinkBallot's data file. Never touches the network.

    python -m pipeline.extract.run       ->  data/extracted/<source>.json  and  data/measures.json

Each field records where it came from: page URL, the raw object (sha256) it was cut from, when it was
fetched, and whether the crawler or a supervised browser capture fetched it.
"""

import importlib
import json
import sys

from ..rawstore import ROOT, RawStore, load_sources

ELECTION = {"id": "ca-2026-11-03", "name": "November 3, 2026 California General Election", "date": "2026-11-03"}
OUT_DIR = ROOT / "data" / "extracted"


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

        def field(text, url, label, _pages=pages):
            row = _pages[url]
            return {"text": text, "source_url": url, "source_label": label,
                    "source_snapshot": str(store.object_path(row["sha256"]).relative_to(ROOT)),
                    "raw_sha256": row["sha256"], "fetched_at": row["fetched_at"],
                    "fetched_by": row["run_kind"]}

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
