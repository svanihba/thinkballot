"""Build data/zip_districts.json: California ZIP (ZCTA) -> likely districts.

Sources are official files only (see SOURCES below and data/zip_districts.SOURCES.md).
Method: every 2020 Census block in California is assigned to a ZCTA (Census
ZCTA-to-block relationship file), to a congressional district (AB 604 /
Proposition 50 block equivalency file), to a State Senate and an Assembly district
(2021 Citizens Redistricting Commission block equivalency files), to a county (block
GEOID) and to a Census place (Census 2020 block assignment file). Block populations
come from the 2020 Census P.L. 94-171 redistricting data (Census API, P1_001N).
For each ZCTA, each district is the one holding the largest share of the ZCTA's
population; the row is marked split when, for any district type, that share is
below SPLIT_THRESHOLD.

Usage: python scripts/build_zip_districts.py [--cache build/zip_districts_cache]
Needs only the Python standard library. Downloads go to the cache dir (gitignored).
"""

import argparse
import csv
import io
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "zip_districts.json")
SPLIT_THRESHOLD = 0.95

SOURCES = {
    # Congressional districts for 2026: AB 604 (Ch. 96, Stats. 2025), adopted by
    # Proposition 50 (Nov 4, 2025 special election, certified Dec 12, 2025).
    "cd_ab604": "https://statewidedatabase.org/pub/data/d25/AB604.zip",
    # State Senate and Assembly: 2021 Citizens Redistricting Commission final maps.
    "sd_crc2021": "https://wedrawthelines.ca.gov/wp-content/uploads/sites/64/2023/01/OneDrive_2023-01-19-4.zip",
    "ad_crc2021": "https://wedrawthelines.ca.gov/wp-content/uploads/sites/64/2023/01/OneDrive_2023-01-19-6.zip",
    # Census 2020 ZCTA <-> tabulation block relationship file (national, ~1 GB).
    "zcta_block": "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_tabblock20_natl.txt",
    # Census 2020 block assignment files for California (block -> place etc.).
    "baf": "https://www2.census.gov/geo/docs/maps-data/data/baf2020/BlockAssign_ST06_CA.zip",
    # Census 2020 place and county names for California.
    "places": "https://www2.census.gov/geo/docs/reference/codes2020/place/st06_ca_place2020.txt",
    "counties": "https://www2.census.gov/geo/docs/reference/codes2020/cou/st06_ca_cou2020.txt",
    # 2020 Census P.L. 94-171 block population (P1_001N), one request per county.
    "pop_api": "https://api.census.gov/data/2020/dec/pl?get=P1_001N&for=block:*&in=state:06%20county:{county}",
}

log = logging.getLogger("build_zip_districts")


def fetch(url, dest, timeout=120, retries=4, line_filter=None):
    """Download url to dest (skipped if dest exists), with timeout, retries, backoff.

    line_filter: optional callable(bytes_line)->bool; when given, the response is
    streamed line by line and only matching lines (plus the header) are written.
    """
    if os.path.exists(dest):
        log.info("cached %s -> %s", url, dest)
        return dest
    tmp = dest + ".part"
    for attempt in range(1, retries + 1):
        log.info("GET %s (attempt %d)", url, attempt)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "thinkballot-build/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp, "wb") as out:
                if line_filter is None:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                else:
                    header = resp.readline()
                    out.write(header)
                    for line in resp:
                        if line_filter(line):
                            out.write(line)
            os.replace(tmp, dest)
            log.info("saved %s (%d bytes)", dest, os.path.getsize(dest))
            return dest
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            log.warning("failed %s: %s", url, exc)
            if attempt == retries:
                raise
            time.sleep(5 * 2 ** (attempt - 1))
    return dest


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(ROOT, "build", "zip_districts_cache"))
    ap.add_argument("--download-only", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    os.makedirs(args.cache, exist_ok=True)
    c = lambda name: os.path.join(args.cache, name)  # noqa: E731

    fetch(SOURCES["cd_ab604"], c("AB604.zip"))
    fetch(SOURCES["sd_crc2021"], c("crc2021_sd_equiv.zip"))
    fetch(SOURCES["ad_crc2021"], c("crc2021_ad_equiv.zip"))
    fetch(SOURCES["baf"], c("BlockAssign_ST06_CA.zip"))
    fetch(SOURCES["places"], c("st06_ca_place2020.txt"))
    fetch(SOURCES["counties"], c("st06_ca_cou2020.txt"))
    if args.download_only:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
