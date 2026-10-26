"""Extractor: California Secretary of State voter guide (statewide propositions).

Reads only raw pages from the raw store. Every field is cut out of the official page by code.
"""

import re

from thinkballot.sourcetext import html_to_text

BASE = "https://voterguide.sos.ca.gov"
GUIDE = "Official Voter Information Guide"
GUIDE_LIST = "Official Voter Information Guide: list of propositions"
LAO = "Analysis by the Legislative Analyst (Official Voter Information Guide)"

# ThinkBallot's topic labels for browsing and search (not official text; checked by Bias Buster).
TOPICS = {
    "1": ["housing", "bonds", "veterans"], "2": ["budget", "state finances"],
    "3": ["taxes", "education", "health care"], "4": ["elections", "campaign finance"],
    "5": ["elections", "recall"], "37": ["housing", "loans"], "38": ["bonds", "medical research"],
    "39": ["elections", "voter ID"], "40": ["taxes"], "41": ["taxes", "state finances"],
    "42": ["taxes", "property"], "43": ["taxes", "local government"], "44": ["health care", "nonprofits"],
    "45": ["environment", "development"],
}


def main_content(raw):
    start = raw.find('id="mainCont"')
    end = raw.find('class="bckToTp"', start)
    if start < 0 or end < 0:
        raise ValueError("unexpected page layout")
    return raw[start:end]


def parse_index(raw):
    out = []
    for num, inner in re.findall(r'<a href="/propositions/(\d+)/"[^>]*>(.*?)</a>', main_content(raw), re.S):
        text = " ".join(html_to_text(inner).split())
        rest = text[len(num):].strip() if text.startswith(num) else text
        m = re.match(r"(.*?)\s((?:Legislative|Initiative|Referendum)\b.*)$", rest)
        if not m:
            raise ValueError(f"can't split title and type for Prop {num}: {rest!r}")
        out.append((num, m.group(1).strip(), m.group(2).strip()))
    return out


def parse_overview(raw):
    main = main_content(raw)
    summary_text = " ".join(html_to_text(re.search(r'<p class="noIndent">(.*?)</p>', main, re.S).group(1)).split())
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
    start, end = text.find("ANALYSIS BY THE LEGISLATIVE ANALYST"), text.find("Visit sos.ca.gov")
    if start < 0:
        raise ValueError("analysis heading not found")
    return text[start + len("ANALYSIS BY THE LEGISLATIVE ANALYST"):end if end > 0 else None].strip()


def extract(pages, field):
    """pages: {url: raw page row}; field(text, url, label) builds a field with provenance."""
    def html(url):
        if url not in pages:
            raise ValueError(f"missing from the raw store: {url}")
        return pages[url]["body"].decode("utf-8")

    index_url = BASE + "/propositions/"
    measures = []
    for num, title, mtype in parse_index(html(index_url)):
        url, analysis_url = f"{BASE}/propositions/{num}/", f"{BASE}/propositions/{num}/analysis.htm"
        ov = parse_overview(html(url))
        fields = {"measure_type": field(mtype, index_url, GUIDE_LIST)}
        for name in ("summary", "yes_means", "no_means", "fiscal_effect", "argument_for", "argument_against",
                     "supporters", "opponents"):
            fields[name] = field(ov[name], url, f"{GUIDE}: Proposition {num}")
        fields["analysis"] = field(parse_analysis(html(analysis_url)), analysis_url, LAO)
        measures.append({
            "id": f"prop-{num}", "number": num, "title": field(title, index_url, GUIDE_LIST),
            "jurisdiction": {"level": "state", "name": "California"},
            "topics": TOPICS.get(num, []), "documents": [],
            "arguments_url": f"{BASE}/propositions/{num}/arguments-rebuttals.htm", "fields": fields,
        })
    return measures
