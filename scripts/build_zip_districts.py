"""Build data/zip_districts.json: California ZIP (ZCTA) -> likely districts.

Sources are official files only (see SOURCES below and data/zip_districts.SOURCES.md).
Method: every 2020 Census block in California is assigned to a ZCTA (Census
ZCTA-to-block relationship file), to a congressional district (AB 604 /
Proposition 50 block equivalency file), to a State Senate and an Assembly district
(2021 Citizens Redistricting Commission block equivalency files), to a county (block
GEOID) and to a Census place (Census 2020 block assignment file). Block populations
come from the 2020 Census P.L. 94-171 redistricting file (P1_001N). All three
district assignments are cross-checked block-for-block against the Census Bureau 2026
block equivalency files (120th Congress, 2026 state legislative districts).
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
    # Same plan as published by the Senate Elections and Constitutional Amendments
    # Committee; used only as a cross-check of the file above.
    "cd_selc_check": "https://selc.senate.ca.gov/media/604",
    # State Senate and Assembly: 2021 Citizens Redistricting Commission final maps.
    "sd_crc2021": "https://wedrawthelines.ca.gov/wp-content/uploads/sites/64/2023/01/OneDrive_2023-01-19-4.zip",
    "ad_crc2021": "https://wedrawthelines.ca.gov/wp-content/uploads/sites/64/2023/01/OneDrive_2023-01-19-6.zip",
    # Census Bureau block equivalency files for the 120th Congress (2026 elections) and
    # the 2026 state legislative districts; used as independent cross-checks.
    "census_cd120": "https://www2.census.gov/programs-surveys/decennial/rdo/mapping-files/2027/120-congressional-district-befs/cd120.zip",
    "census_sldu26": "https://www2.census.gov/programs-surveys/decennial/rdo/mapping-files/2027/2026-state-legislative-bef/sldu26.zip",
    "census_sldl26": "https://www2.census.gov/programs-surveys/decennial/rdo/mapping-files/2027/2026-state-legislative-bef/sldl26.zip",
    # Census 2020 ZCTA <-> tabulation block relationship file (national, ~1 GB).
    "zcta_block": "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_tabblock20_natl.txt",
    # Census 2020 block assignment files for California (block -> place etc.).
    "baf": "https://www2.census.gov/geo/docs/maps-data/data/baf2020/BlockAssign_ST06_CA.zip",
    # Census 2020 place and county names for California.
    "places": "https://www2.census.gov/geo/docs/reference/codes2020/place/st06_ca_place2020.txt",
    "counties": "https://www2.census.gov/geo/docs/reference/codes2020/cou/st06_ca_cou2020.txt",
    # 2020 Census P.L. 94-171 redistricting data for California (block population P1_001N).
    "pl94171": "https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/California/ca2020.pl.zip",
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
    fetch(SOURCES["cd_selc_check"], c("selc_ab604_equiv.csv"))
    # National file is ~1 GB: stream it and keep only California blocks.
    fetch(SOURCES["zcta_block"], c("zcta_block_ca.txt"), timeout=300,
          line_filter=lambda line: line.split(b"|", 10)[9].startswith(b"06"))
    fetch(SOURCES["pl94171"], c("ca2020.pl.zip"), timeout=300)
    for key in ("census_cd120", "census_sldu26", "census_sldl26"):
        fetch(SOURCES[key], c(key + ".zip"), timeout=300)
    counties = read_pipe(c("st06_ca_cou2020.txt"))
    if args.download_only:
        return 0

    county_names = {r["COUNTYFP"]: strip_suffix(r["COUNTYNAME"], (" County",)) for r in counties}
    place_names = {r["PLACEFP"]: strip_suffix(r["PLACENAME"], (" city", " town", " CDP"))
                   for r in read_pipe(c("st06_ca_place2020.txt"))}

    cd = read_equiv(c("AB604.zip"), "AB604.csv")
    sd = read_equiv(c("crc2021_sd_equiv.zip"), "SD_Final equiv 2/SD Iteration 1218.csv")
    ad = read_equiv(c("crc2021_ad_equiv.zip"),
                    "AD Final Equivalency/CRC_2021_Assembly_Final equivalency.csv")
    with open(c("selc_ab604_equiv.csv"), encoding="utf-8-sig") as fh:
        selc = {}
        for rec in csv.reader(fh):
            if rec and rec[0].isdigit():
                selc[rec[0]] = str(int(rec[1]))
    if selc != cd:
        diff = sum(1 for k in set(cd) | set(selc) if cd.get(k) != selc.get(k))
        raise SystemExit(f"AB 604 equivalency files disagree on {diff} blocks")
    log.info("AB 604 Statewide Database and Senate Elections Committee files agree (%d blocks)", len(cd))

    for name, ours, key, member in (
        ("congressional", cd, "census_cd120", "CD120_06.txt"),
        ("state_senate", sd, "census_sldu26", "NationalSLDU26.txt"),
        ("assembly", ad, "census_sldl26", "NationalSLDL26.txt"),
    ):
        theirs = read_census_bef(c(key + ".zip"), member)
        diff = sum(1 for k in set(ours) | set(theirs) if ours.get(k) != theirs.get(k))
        if diff:
            raise SystemExit(f"{name}: state file and Census 2026 BEF disagree on {diff} blocks")
        log.info("%s: state file matches Census BEF %s on all %d blocks", name, key, len(ours))

    with zipfile.ZipFile(c("BlockAssign_ST06_CA.zip")) as zf:
        text = zf.read("BlockAssign_ST06_CA_INCPLACE_CDP.txt").decode("ascii")
    place = {}
    for rec in csv.DictReader(io.StringIO(text), delimiter="|"):
        if rec["PLACEFP"]:
            place[rec["BLOCKID"]] = rec["PLACEFP"]

    pop = read_pl_block_population(c("ca2020.pl.zip"))
    log.info("block populations: %d blocks, %d people", len(pop), sum(pop.values()))

    zcta_blocks = defaultdict(list)  # zcta -> [(block, land_area)]
    with open(c("zcta_block_ca.txt"), encoding="utf-8-sig") as fh:
        for rec in csv.DictReader(fh, delimiter="|"):
            z = rec["GEOID_ZCTA5_20"]
            if z:
                zcta_blocks[z].append((rec["GEOID_TABBLOCK_20"], int(rec["AREALAND_PART"] or 0)))

    for name, table in (("congressional", cd), ("state_senate", sd), ("assembly", ad), ("population", pop)):
        if set(table) != set(pop):
            raise SystemExit(f"{name}: block set differs from Census population blocks")

    zips, skipped = {}, []
    for z in sorted(zcta_blocks):
        blocks = zcta_blocks[z]
        total_pop = sum(pop[b] for b, _ in blocks)
        weight_basis = "population"
        weights = [(b, pop[b]) for b, _ in blocks]
        if total_pop == 0:
            weight_basis = "land_area"
            weights = [(b, a) for b, a in blocks]
            if sum(a for _, a in weights) == 0:
                weights = [(b, 1) for b, _ in blocks]
                weight_basis = "block_count"
        if not ("90000" <= z <= "96999"):
            skipped.append((z, total_pop))
            continue
        row, shares, split = {}, {}, False
        for key, table in (("congressional", cd), ("state_senate", sd), ("assembly", ad)):
            best, share = plurality(weights, table.get)
            row[key] = best
            shares[key] = round(share, 3)
            split = split or share < SPLIT_THRESHOLD
        county, _ = plurality(weights, lambda b: county_names[b[2:5]])
        pfp, pshare = plurality(weights, place.get)
        row = {
            "city": place_names[pfp] if pfp else "",
            "county": county,
            **row,
            "split": split,
            "shares": shares,
            "population": total_pop,
        }
        if weight_basis != "population":
            row["weight"] = weight_basis
        zips[z] = row

    for z, p in skipped:
        log.warning("skipped ZCTA %s (outside the 90000-96999 California range), CA pop %d", z, p)

    note = (
        "California ZIP code (2020 Census ZCTA) -> likely districts for the 3 Nov 2026 election. "
        "Congressional: AB 604 (Ch. 96, Stats. 2025) districts adopted by Proposition 50 (approved "
        "Nov 4, 2025; certified Dec 12, 2025), block equivalency file " + SOURCES["cd_ab604"] +
        " (cross-checked identical to " + SOURCES["cd_selc_check"] + "). State Senate: 2021 Citizens "
        "Redistricting Commission final map, block equivalency " + SOURCES["sd_crc2021"] + ". Assembly: "
        "2021 Citizens Redistricting Commission final map, block equivalency " + SOURCES["ad_crc2021"] +
        ". All three district assignments were checked block-for-block to be identical to the Census "
        "Bureau block equivalency files for the 120th Congress and the 2026 state legislative districts: "
        + SOURCES["census_cd120"] + ", " + SOURCES["census_sldu26"] + ", " + SOURCES["census_sldl26"] +
        ". Blocks -> ZCTA: " + SOURCES["zcta_block"] + ". Block population: 2020 Census P.L. 94-171 "
        "P1_001N (total population) from " + SOURCES["pl94171"] + ". City: Census 2020 place (incorporated "
        "place or CDP) from " + SOURCES["baf"] + " with names from " + SOURCES["places"] + "; county "
        "names from " + SOURCES["counties"] + ". Method: each ZCTA gets, per district type, the "
        "district holding the largest share of its 2020 population (land area for unpopulated ZCTAs); "
        "'shares' gives that share and 'split' is true when any share is below "
        f"{SPLIT_THRESHOLD:.0%}. 'city' is the Census place holding the most population (empty if most "
        "people live outside any place); it can differ from the USPS city name. ZIP codes are not "
        "district boundaries: split ZIPs need a full address. Built by scripts/build_zip_districts.py."
    )
    with open(OUT, "w") as fh:
        json.dump({"_note": note, "zips": zips}, fh, indent=1, sort_keys=False)
        fh.write("\n")
    log.info("wrote %s: %d ZIPs, %d split", OUT, len(zips), sum(r["split"] for r in zips.values()))
    return 0


def read_pl_block_population(zip_path):
    """{15-digit block GEOID: total population} from the 2020 P.L. 94-171 files.

    Geographic header (ca geo2020.pl): field 2 SUMLEV, 7 LOGRECNO, 9 GEOCODE.
    Segment 1 (ca000012020.pl): field 4 LOGRECNO, 5 P0010001 (total population).
    """
    with zipfile.ZipFile(zip_path) as zf:
        logrec_block = {}
        with zf.open("cageo2020.pl") as fh:
            for line in io.TextIOWrapper(fh, encoding="latin-1"):
                f = line.rstrip("\r\n").split("|")
                if f[2] == "750":
                    logrec_block[f[7]] = f[9]
        pop = {}
        with zf.open("ca000012020.pl") as fh:
            for line in io.TextIOWrapper(fh, encoding="latin-1"):
                f = line.split("|", 6)
                block = logrec_block.get(f[4])
                if block:
                    pop[block] = int(f[5])
    return pop


def read_census_bef(zip_path, member):
    """Census BEF (GEOID,STATEFP,COUNTYFP,TRACTCE,BLOCKCE,district) -> California blocks."""
    out = {}
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as fh:
        for line in io.TextIOWrapper(fh, encoding="utf-8-sig"):
            f = line.rstrip("\r\n").split(",")
            if f[1] == "06":
                out[f[0]] = str(int(f[5]))
    return out


def read_pipe(path):
    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh, delimiter="|"))


def strip_suffix(name, suffixes):
    for s in suffixes:
        if name.endswith(s):
            return name[: -len(s)]
    return name


def read_equiv(zip_path, member):
    """Block equivalency CSV ("block GEOID","district") -> {block: district number as str}."""
    with zipfile.ZipFile(zip_path) as zf:
        text = zf.read(member).decode("utf-8-sig")
    out = {}
    for rec in csv.reader(io.StringIO(text)):
        if rec:
            out[rec[0]] = str(int(rec[1]))
    return out


def plurality(weights, key):
    """(value with the largest total weight, its share). Blocks whose key is None count
    toward the total but not toward any value."""
    tot = defaultdict(float)
    total = 0
    for b, w in weights:
        total += w
        v = key(b)
        if v is not None:
            tot[v] += w
    if not tot:
        return None, 0.0
    best = max(sorted(tot), key=lambda v: tot[v])
    return best, (tot[best] / total if total else 0.0)


if __name__ == "__main__":
    sys.exit(main())
