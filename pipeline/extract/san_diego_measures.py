"""Extractor: San Diego County Registrar of Voters, local measures for November 3, 2026.

Source: the county's printed Voter Information Pamphlet and Sample Ballot, one PDF per ballot type
(sdvote.com/content/dam/rov/en/sb/SB-ENG-<type>.pdf). The ROV publishes no single list of measures with
their letters, so the source file seeds the few ballot types that together carry every local measure
on the ballot anywhere in the county (county, city, school and special district measures). EXPECTED
below is that list; extraction fails if any measure is missing or an unknown one appears.

Each measure is cut from two places in a pamphlet, which must agree:
- the measure section: "<JURISDICTION>" / "MEASURE X" / "(This measure will appear on the ballot in the
  following form.)" / "MEASURE X" / [title in capitals] / question / "This measure requires <vote>
  of those voting on the measure." The question's words are sometimes run together here
  ("updateterminology"), because the PDF text loses a space;
- the ballot page itself ("MEASURE X <title and question>" in a narrow column, ending in "YES NO" or
  "BONDS - YES BONDS - NO"), which keeps the spaces.
The two must be the same text when spaces are ignored; the reading with more words (spaces kept) is used.
A measure that appears in several pamphlets must read the same in all of them. Anything else raises.
"""

import re

LABEL = "San Diego County Registrar of Voters: Voter Information Pamphlet and Sample Ballot, ballot type {bt}"
URL_RE = re.compile(r"^https://www\.sdvote\.com/content/dam/rov/en/sb/SB-ENG-(\d+)\.pdf$")
COUNTY = "San Diego"
CODE = "sd"

# Every local measure on the November 3, 2026 ballot in San Diego County: letter -> jurisdiction as printed.
EXPECTED = {
    "A": "SAN DIEGO COUNTY", "B": "SAN DIEGO COUNTY",
    "C": "CITY OF SOLANA BEACH", "D": "CITY OF CORONADO", "E": "CITY OF LEMON GROVE",
    "G": "GROSSMONT-CUYAMACA COMMUNITY COLLEGE DISTRICT", "H": "JAMUL-DULZURA UNION SCHOOL DISTRICT",
    "J": "JULIAN UNION HIGH SCHOOL DISTRICT", "K": "FALLBROOK UNION ELEMENTARY SCHOOL DISTRICT",
    "L": "MOUNTAIN EMPIRE UNIFIED SCHOOL DISTRICT", "M": "SAN DIEGO UNIFIED SCHOOL DISTRICT",
    "N": "VISTA UNIFIED SCHOOL DISTRICT", "P": "RAMONA MUNICIPAL WATER DISTRICT",
    "Q": None, "R": "CITY OF OCEANSIDE", "S": "CITY OF OCEANSIDE", "T": None,
    "Y": "CITY OF SANTEE", "AA": "LA MESA-SPRING VALLEY SCHOOL DISTRICT", "BB": "SANTEE SCHOOL DISTRICT",
}

SECTION_RE = re.compile(
    r"^SD \d{3}-\d{3}\n(?P<head>(?:[^\n]+\n){1,3}?)MEASURE (?P<letter>[A-Z]{1,2})\n(?:`\n)?PR-[A-Z0-9]+-\d+-ENG\n"
    r"\((?i:this measure will appear on the ballot in the following form)\.\)\nMEASURE (?P=letter)\n"
    r"(?P<body>.*?)\nThis measure requires (?P<vote>[^\n]+?) of those voting on the measure\.$", re.M | re.S)
BALLOT_RE = re.compile(r"^MEASURE (?P<letter>[A-Z]{1,2}) (?P<body>.+?)\n(?:YES NO|BONDS - YES BONDS - NO)$",
                       re.M | re.S)
BONDS_LINE = "Bonds – Yes Bonds – No"
SMALL = {"of", "and", "the"}


def display_name(name):
    """'CITY OF SOLANA BEACH' -> 'City of Solana Beach'; 'LA MESA-SPRING VALLEY' -> 'La Mesa-Spring Valley'."""
    def word(w, first):
        if any(c.isdigit() for c in w):
            return w
        if not first and w.lower() in SMALL:
            return w.lower()
        return "-".join(p.capitalize() for p in w.split("-"))
    return " ".join(word(w, i == 0) for i, w in enumerate(name.split()))


def _squash(text):
    return re.sub(r"\s+", "", text)


def _words(text):
    return " ".join(text.split())


def sections(text):
    """{letter: (jurisdiction, body, vote)} from one pamphlet's measure sections."""
    found = {}
    for m in SECTION_RE.finditer(text):
        letter = m.group("letter")
        head = _words(m.group("head"))
        if letter in found:
            raise ValueError(f"Measure {letter}: two measure sections in one pamphlet")
        found[letter] = (head, m.group("body"), m.group("vote"))
    # Every section header must have been parsed; a header the pattern missed means a changed layout.
    headers = re.findall(r"^\((?i:this measure will appear on the ballot in the following form)\.\)\nMEASURE ([A-Z]{1,2})$",
                         text, re.M)
    if sorted(headers) != sorted(found):
        raise ValueError(f"measure sections {sorted(headers)} but parsed {sorted(found)}")
    return found


def ballot_blocks(text):
    """{letter: text} of each measure as printed on the ballot pages."""
    out = {}
    for m in BALLOT_RE.finditer(text):
        if m.group("letter") in out:
            raise ValueError(f"Measure {m.group('letter')} printed twice on the ballot")
        out[m.group("letter")] = _words(m.group("body"))
    return out


def parse_measure(letter, head, body, vote, printed):
    """(title or None, question) for one measure, checked against its ballot-page text."""
    lines = body.split("\n")
    if lines and lines[-1] == BONDS_LINE:
        lines.pop()
    if any("Bonds – " in line for line in lines):
        raise ValueError(f"Measure {letter}: unexpected bonds line in the question")
    title_lines = []
    while lines and not re.search(r"[a-z]", lines[0]):
        title_lines.append(lines.pop(0))
    section = _words(" ".join(title_lines + lines))
    if printed is None:
        raise ValueError(f"Measure {letter}: not printed on the ballot pages")
    # The ballot page sometimes prints a bulleted list's bullets out of order in the PDF text, so bullets
    # are left out of the comparison; when the word counts agree, the section (bullets in place) is used.
    if _squash(section.replace("•", "")) != _squash(printed.replace("•", "")):
        raise ValueError(f"Measure {letter}: the measure section and the ballot page differ")
    n_section, n_printed = (len(t.replace("•", "").split()) for t in (section, printed))
    if n_section >= n_printed:
        chosen = section
    elif "•" not in printed:
        chosen = printed
    else:
        raise ValueError(f"Measure {letter}: words run together in the section, and the ballot page has bullets")
    title, question = None, chosen
    if title_lines:
        want, taken, words = len(_squash(" ".join(title_lines))), 0, chosen.split()
        for i, w in enumerate(words):
            taken += len(w)
            if taken == want:
                title, question = " ".join(words[:i + 1]), " ".join(words[i + 1:])
                break
            if taken > want:
                raise ValueError(f"Measure {letter}: the title does not end at a word boundary")
    if not question.endswith("?") and "?" not in question:
        raise ValueError(f"Measure {letter}: no ballot question")
    if len(question.split()) < 15:
        raise ValueError(f"Measure {letter}: ballot question too short: {question!r}")
    return title, question


def pamphlet_measures(text):
    """{letter: {jurisdiction, title, question, vote}} from one pamphlet."""
    if "GUBERNATORIAL GENERAL ELECTION" not in text or "NOVEMBER 3, 2026" not in text:
        raise ValueError("not a November 3, 2026 pamphlet")
    printed = ballot_blocks(text)
    out = {}
    for letter, (head, body, vote) in sections(text).items():
        title, question = parse_measure(letter, head, body, vote, printed.get(letter))
        out[letter] = {"jurisdiction": head, "title": title, "question": question, "vote": vote}
    return out


def extract(pages, field):
    pdfs = sorted((int(URL_RE.match(u).group(1)), u) for u in pages if URL_RE.match(u))
    if not pdfs:
        raise ValueError("no sample ballot PDFs in the raw store")
    found = {}
    for bt, url in pdfs:
        if "text" not in pages[url]:
            raise ValueError(f"{url}: not a PDF")
        for letter, m in pamphlet_measures(pages[url]["text"]).items():
            if letter in found:
                first = found[letter][2]
                if first != m:
                    raise ValueError(f"Measure {letter} reads differently in ballot types {found[letter][0]} and {bt}")
                continue
            found[letter] = (bt, url, m)
    if set(found) != set(EXPECTED):
        raise ValueError(f"measures missing {sorted(set(EXPECTED) - set(found))}, "
                         f"unexpected {sorted(set(found) - set(EXPECTED))}")
    measures = []
    for letter in sorted(found, key=lambda x: (len(x), x)):
        bt, url, m = found[letter]
        if EXPECTED[letter] and m["jurisdiction"] != EXPECTED[letter]:
            raise ValueError(f"Measure {letter}: jurisdiction {m['jurisdiction']!r}, expected {EXPECTED[letter]!r}")
        label = LABEL.format(bt=bt)
        name = display_name(m["jurisdiction"])
        measures.append({
            "id": f"local-{CODE}-{letter.lower()}", "number": letter,
            "title": field(m["title"] or name, url, label),
            "jurisdiction": {"level": "local", "county": COUNTY, "name": name},
            "topics": [], "arguments_url": None,
            "notes": ["Ballot question as printed in the San Diego County sample ballot and voter information "
                      f"pamphlet (ballot type {bt})."],
            "documents": [{"label": f"San Diego County sample ballot and voter information pamphlet, "
                                    f"ballot type {bt} (PDF; Measure {letter} with its analysis and arguments)",
                           "url": url}],
            "fields": {
                "measure_type": field(m["vote"], url, label),
                "district": field(m["jurisdiction"], url, label),
                "ballot_question": field(m["question"], url, label),
            },
        })
    return measures
