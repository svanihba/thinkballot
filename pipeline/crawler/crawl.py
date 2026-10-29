"""The crawler: fetches pages and stores them raw. It never interprets content.

    python -m pipeline.crawler.crawl [source-id ...]      # default: every source in pipeline/sources.json

Rules it always follows:
- identifies itself honestly (USER_AGENT) and obeys robots.txt;
- waits `delay_seconds` between requests to the same source; timeout, 3 tries with backoff;
- follows only links matching the source's `allow` patterns, up to `max_depth` hops;
- when a site refuses automated access (robots.txt, or a 403/429/503 challenge page) it records the
  block and moves on. It never tries to get around one.
"""

import re
import sys
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests

from ..rawstore import RawStore, load_sources

USER_AGENT = "ThinkBallotBot/0.1 (+https://www.thinkballot.com/about; nonpartisan voter guide)"
TIMEOUT = 30
TRIES = 3
HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#]+)""", re.IGNORECASE)


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Robots:
    def __init__(self, session):
        self.session, self.cache = session, {}

    def allowed(self, url):
        origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
        if origin not in self.cache:
            rp = urllib.robotparser.RobotFileParser()
            try:
                resp = self.session.get(origin + "/robots.txt", timeout=TIMEOUT)
                if resp.status_code == 200 and "text/plain" in resp.headers.get("content-type", ""):
                    rp.parse(resp.text.splitlines())
                elif 400 <= resp.status_code < 500:
                    rp.allow_all = True  # RFC 9309: robots.txt "unavailable" (4xx) means no rules
                else:
                    rp.disallow_all = True  # 5xx / unreachable: RFC 9309 says assume complete disallow
            except requests.RequestException:
                rp.disallow_all = True
            self.cache[origin] = rp
        return self.cache[origin].can_fetch(USER_AGENT, url)


def looks_blocked(resp):
    if resp.status_code in (403, 429, 503):
        body = resp.text[:3000].lower()
        return resp.status_code == 429 or "cloudflare" in body or "attention required" in body \
            or "captcha" in body or "access denied" in body or resp.status_code == 403
    return False


def get(session, url, headers):
    last = None
    for attempt in range(1, TRIES + 1):
        started = time.monotonic()
        try:
            resp = session.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
            log(f"GET {url} -> {resp.status_code} {len(resp.content)} B in {time.monotonic() - started:.1f}s")
            if resp.status_code >= 500 and attempt < TRIES and not looks_blocked(resp):
                time.sleep(2 ** attempt)
                continue
            return resp, None
        except requests.RequestException as exc:
            last = type(exc).__name__
            log(f"GET {url} attempt {attempt} failed: {last}")
            time.sleep(2 ** attempt)
    return None, last


def crawl_source(store, source):
    sid = source["id"]
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"})
    robots = Robots(session)
    allow = [re.compile(p) for p in source.get("allow", [])]
    run = store.start_run(sid, "crawl", USER_AGENT)
    queue = [(u, None, 0) for u in source["seeds"]]
    seen, stored, blocked, failed = set(), 0, 0, 0
    while queue:
        url, parent, depth = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if not robots.allowed(url):
            log(f"robots.txt disallows {url} - skipped")
            store.record(run, sid, url, parent_url=parent, depth=depth, blocked=1, error="robots.txt disallows")
            blocked += 1
            continue
        prev = store.last_good(sid, url)
        headers = {}
        if prev and prev["etag"]:
            headers["If-None-Match"] = prev["etag"]
        if prev and prev["last_modified"]:
            headers["If-Modified-Since"] = prev["last_modified"]
        resp, err = get(session, url, headers)
        time.sleep(source.get("delay_seconds", 1))
        if resp is None:
            store.record(run, sid, url, parent_url=parent, depth=depth, error=err)
            failed += 1
            continue
        meta = dict(parent_url=parent, depth=depth, final_url=resp.url, http_status=resp.status_code,
                    content_type=resp.headers.get("content-type"), etag=resp.headers.get("etag"),
                    last_modified=resp.headers.get("last-modified"))
        if looks_blocked(resp):
            log(f"BLOCKED by the site ({resp.status_code}) - recorded, not retried: {url}")
            store.record(run, sid, url, blocked=1, error="site refuses automated access", **meta)
            blocked += 1
            continue
        if resp.status_code == 304 and prev:
            # a 304 carries no content type; the stored copy's type decides whether its links are followed
            meta["content_type"] = meta["content_type"] or store.stored_content_type(sid, url, prev["sha256"])
            store.record(run, sid, url, sha256=prev["sha256"], size=prev["size"], unchanged=1, **meta)
            body = store.read(prev["sha256"])
        elif resp.status_code == 200:
            body = resp.content
            sha = store.put(body)
            store.record(run, sid, url, sha256=sha, size=len(body),
                         unchanged=int(bool(prev and prev["sha256"] == sha)), **meta)
            stored += 1
        else:
            store.record(run, sid, url, error=f"HTTP {resp.status_code}", **meta)
            failed += 1
            continue
        if depth < source.get("max_depth", 0) and "html" in (meta["content_type"] or ""):
            for href in HREF_RE.findall(body.decode("utf-8", "replace")):
                link = urljoin(resp.url, href.strip())
                if any(p.match(link) for p in allow) and link not in seen:
                    queue.append((link, url, depth + 1))
    status = "blocked" if blocked and not stored else "partial" if blocked or failed else "ok"
    store.finish_run(run, status)
    log(f"source {sid}: {status} - stored {stored}, blocked {blocked}, failed {failed}, seen {len(seen)}")
    return status


def main(argv):
    sources = load_sources()
    ids = argv or list(sources)
    store = RawStore()
    for sid in ids:
        crawl_source(store, sources[sid])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
