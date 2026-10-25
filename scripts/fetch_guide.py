"""Copy the 3-Nov-2026 statewide propositions, word for word, from the official voter guide.

    python scripts/fetch_guide.py

Saves each source page under data/sources/2026-11-03/ and writes data/measures.json.
Every field is cut out of the official page by code (no AI, no retyping). Topics are ThinkBallot's own
labels from TOPICS below; the seed script checks them with Bias Buster.
"""

import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from thinkballot.sourcetext import html_to_text  # noqa: E402

BASE = "https://voterguide.sos.ca.gov"
ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / "data" / "sources" / "2026-11-03"
OUT = ROOT / "data" / "measures.json"
GUIDE = "Official Voter Information Guide"
GUIDE_LIST = "Official Voter Information Guide: list of propositions"
LAO = "Analysis by the Legislative Analyst (Official Voter Information Guide)"

ELECTION = {"id": "ca-2026-11-03", "name": "November 3, 2026 California General Election", "date": "2026-11-03"}

# ThinkBallot's topic labels for browsing and search (not official text; checked by Bias Buster).
TOPICS = {
    "1": ["housing", "bonds", "veterans"],
    "2": ["budget", "state finances"],
    "3": ["taxes", "education", "health care"],
    "4": ["elections", "campaign finance"],
    "5": ["elections", "recall"],
    "37": ["housing", "loans"],
    "38": ["bonds", "medical research"],
    "39": ["elections", "voter ID"],
    "40": ["taxes"],
    "41": ["taxes", "state finances"],
    "42": ["taxes", "property"],
    "43": ["taxes", "local government"],
    "44": ["health care", "nonprofits"],
    "45": ["environment", "development"],
}


def fetch(url, name):
    """Download a page (timeout, 3 tries, a log line each) and save a copy for the record."""
    for attempt in range(1, 4):
        started = time.monotonic()
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "ThinkBallot data fetch"})
            print(f"GET {url} -> {resp.status_code} in {time.monotonic() - started:.1f}s")
            resp.raise_for_status()
            text = resp.content.decode("utf-8")  # the guide is UTF-8 but doesn't always say so in headers
            (SNAP_DIR / name).write_text(text)
            return text
        except requests.RequestException as exc:
            print(f"  attempt {attempt} failed: {type(exc).__name__}")
            time.sleep(2 * attempt)
    raise SystemExit(f"Could not fetch {url}")


def main_content(raw):
    """The page's main column, without the site navigation."""
    start = raw.find('id="mainCont"')
    end = raw.find('class="bckToTp"', start)
    if start < 0 or end < 0:
        raise ValueError("unexpected page layout")
    return raw[start:end]


def field(text, url, label, snapshot):
    return {"text": text, "source_url": url, "source_label": label, "source_snapshot": snapshot}


def parse_index(raw):
    """[(number, title, measure_type)] in ballot order, from the propositions list."""
    out = []
    for num, inner in re.findall(r'<a href="/propositions/(\d+)/"[^>]*>(.*?)</a>', main_content(raw), re.S):
        text = " ".join(html_to_text(inner).split())
        rest = text[len(num):].strip() if text.startswith(num) else text
        # "Authorizes Bonds for Housing Affordability Programs. Legislative Statute."
        m = re.match(r"(.*?)\s((?:Legislative|Initiative|Referendum)\b.*)$", rest)
        if not m:
            raise ValueError(f"can't split title and type for Prop {num}: {rest!r}")
        out.append((num, m.group(1).strip(), m.group(2).strip()))
    return out


def parse_overview(raw):
    main = main_content(raw)
    summary_p = re.search(r'<p class="noIndent">(.*?)</p>', main, re.S).group(1)
    summary_text = " ".join(html_to_text(summary_p).split())
    m = re.match(r"(.*?)\s*Fiscal Impact\s*:\s*(.*?)\s*Supporters\s*:\s*(.*?)\s*Opponents\s*:\s*(.*)$", summary_text)
    if not m:
        raise ValueError("can't split the summary paragraph")
    summary, fiscal, supporters, opponents = (g.strip() for g in m.groups())

    def after_label(label):
        para = re.search(r'<span class="yesNoProCon">' + label + r"</span>(.*?)</p>", main, re.S).group(1)
        return " ".join(html_to_text(para).split())

    return {"summary": summary, "fiscal_effect": fiscal, "supporters": supporters, "opponents": opponents,
            "yes_means": after_label("YES"), "no_means": after_label("NO"),
            "argument_for": after_label("PRO"), "argument_against": after_label("CON")}


def parse_analysis(raw):
    text = html_to_text(main_content(raw))
    start = text.find("ANALYSIS BY THE LEGISLATIVE ANALYST")
    end = text.find("Visit sos.ca.gov")
    if start < 0:
        raise ValueError("analysis heading not found")
    body = text[start + len("ANALYSIS BY THE LEGISLATIVE ANALYST"):end if end > 0 else None]
    return body.strip()


def main():
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    rel = lambda name: str((SNAP_DIR / name).relative_to(ROOT))  # noqa: E731
    index_url = BASE + "/propositions/"
    props = parse_index(fetch(index_url, "index.html"))
    print(f"{len(props)} propositions: {', '.join(n for n, _, _ in props)}")

    measures = []
    for num, title, mtype in props:
        url = f"{BASE}/propositions/{num}/"
        analysis_url = f"{BASE}/propositions/{num}/analysis.htm"
        ov = parse_overview(fetch(url, f"prop{num}.html"))
        analysis = parse_analysis(fetch(analysis_url, f"prop{num}-analysis.html"))
        fields = {"measure_type": field(mtype, index_url, GUIDE_LIST, rel("index.html"))}
        for name in ("summary", "yes_means", "no_means", "fiscal_effect", "argument_for", "argument_against",
                     "supporters", "opponents"):
            fields[name] = field(ov[name], url, f"{GUIDE}: Proposition {num}", rel(f"prop{num}.html"))
        fields["analysis"] = field(analysis, analysis_url, LAO, rel(f"prop{num}-analysis.html"))
        measures.append({
            "id": f"prop-{num}", "number": num,
            "title": field(title, index_url, GUIDE_LIST, rel("index.html")),
            "topics": TOPICS.get(num, []),
            "arguments_url": f"{BASE}/propositions/{num}/arguments-rebuttals.htm",
            "fields": fields,
        })
        time.sleep(0.5)  # be polite to the state's server

    OUT.write_text(json.dumps({"_note": "Copied word for word from the Official Voter Information Guide by "
                                        "scripts/fetch_guide.py. Do not edit by hand.",
                               "election": ELECTION, "measures": measures}, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {OUT.relative_to(ROOT)} with {len(measures)} measures.")


if __name__ == "__main__":
    main()
