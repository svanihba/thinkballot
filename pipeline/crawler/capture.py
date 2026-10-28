"""Add a page saved during a supervised browser session to the raw store.

For sites that refuse automated clients: a person opens the page in a real browser and saves it;
this records it exactly like a crawled page, but marked kind='capture' with who captured it.

    python -m pipeline.crawler.capture --source santa-clara-local-measures-2026-11 \\
        --url https://vote.santaclaracounty.gov/list-local-measures-4 --file page.html \\
        --by "Abhinav (supervised browser session)"
"""

import argparse
import sys
from pathlib import Path

from ..rawstore import RawStore, load_sources


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True)
    p.add_argument("--url", required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--by", required=True, help="who captured it, in which session")
    a = p.parse_args(argv)
    if a.source not in load_sources():
        sys.exit(f"unknown source {a.source}")
    body = Path(a.file).read_bytes()
    store = RawStore()
    run = store.start_run(a.source, "capture", a.by, notes="saved from a real browser; site blocks crawlers")
    prev = store.last_good(a.source, a.url)
    sha = store.put(body)
    content_type = ("application/pdf" if body[:5] == b"%PDF-" else "application/json" if body[:1] in b"{["
                    else "text/html; charset=utf-8")
    store.record(run, a.source, a.url, final_url=a.url, http_status=200, content_type=content_type,
                 sha256=sha, size=len(body), unchanged=int(bool(prev and prev["sha256"] == sha)))
    store.finish_run(run, "ok")
    print(f"captured {a.url} -> {sha[:12]} ({len(body)} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
