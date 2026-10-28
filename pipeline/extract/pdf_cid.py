"""Text of PDFs whose CJK font has no Unicode table (ToUnicode), read by code, not by OCR.

The Secretary of State's Chinese voter guide sets Chinese in Source Han Sans TW, embedded as a CID font
with Identity-H encoding (character code = CID) and no ToUnicode table. Text tools then print each CID
as if it were a character: random-looking symbols, and the font's own digits and brackets (CIDs below
32) vanish as control characters. So this module reads the page content itself:

- qpdf (Homebrew, like poppler) decodes the PDF's objects and streams to JSON; nothing is rendered;
- each text-showing operator gives its font, its character codes and its position on the page;
- codes become characters through the font's ToUnicode table when it has one (the Latin fonts), and
  otherwise, for Source Han Sans, through the font's own published CMap reversed
  (pipeline/cmaps/UniSourceHan*-UTF16-H from Adobe's Source Han Sans 1.004 release, BSD licence; the
  guide embeds that version's CIDs). This is a fixed table lookup: nothing is guessed or translated.
  A font with neither table, or a code missing from it, gives U+FFFD, and extractors refuse any field
  containing one.

The result is runs of text with positions, in the order the page draws them, so an extractor can cut
fields out by where they sit on the page; pdf_text() is the saved reading the seed verifies against.
"""

import base64
import json
import math
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

CMAP_DIR = Path(__file__).resolve().parent.parent / "cmaps"
CJK_FONTS = {"SourceHanSansTW": "UniSourceHanSansTW-UTF16-H", "SourceHanSansJP": "UniSourceHanSansJP-UTF16-H"}
UNKNOWN = "�"

# Characters written without spaces between them: CJK ideographs, kana, CJK and full-width punctuation.
CJK = ("⺀-⿿　-〿぀-ヿ㄀-ㄯ㐀-䶿一-鿿豈-﫿"
       "︰-﹏＀-￯")
CJK_RE = re.compile(f"[{CJK}]")


# ---------- character tables ----------

def _u16(hexstr):
    return bytes.fromhex(hexstr).decode("utf-16-be", "replace")


def _variant_rank(ch):
    o = ord(ch[0])
    if 0x2E80 <= o <= 0x2FDF or 0xF900 <= o <= 0xFAFF or 0x2F800 <= o <= 0x2FA1F:
        return 2  # radicals and compatibility ideographs
    if 0xFE30 <= o <= 0xFE4F:
        return 1  # vertical forms
    return 0


@lru_cache(maxsize=None)
def cid_table(name):
    """{CID: character} from an Adobe UTF-16 CMap. Where several characters share one glyph, the
    ordinary character wins over a Kangxi radical, a radical supplement form, a vertical form or a
    compatibility ideograph (行 U+884C, not ⾏ U+2F8F); then the lowest code point."""
    text = (CMAP_DIR / name).read_text(encoding="latin-1")
    pairs = []
    for block in re.findall(r"begincidrange(.*?)endcidrange", text, re.S):
        for lo, hi, cid in re.findall(r"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>\s*(\d+)", block):
            lo_c, hi_c = _u16(lo), _u16(hi)
            for i in range(ord(hi_c) - ord(lo_c) + 1):
                pairs.append((int(cid) + i, chr(ord(lo_c) + i)))
    for block in re.findall(r"begincidchar(.*?)endcidchar", text, re.S):
        for code, cid in re.findall(r"<([0-9a-fA-F]+)>\s*(\d+)", block):
            pairs.append((int(cid), _u16(code)))
    table = {}
    for cid, ch in sorted(pairs, key=lambda p: (p[0], _variant_rank(p[1]), p[1])):
        table.setdefault(cid, ch)
    return table


def _to_unicode(data):
    """{code: text} from a ToUnicode CMap stream."""
    text = data.decode("latin-1")
    table = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]*)>", block):
            table[int(src, 16)] = _u16(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, dst in re.findall(r"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>\s*(<[0-9a-fA-F]*>|\[[^\]]*\])", block):
            lo, hi = int(lo, 16), int(hi, 16)
            if dst.startswith("["):
                for i, d in enumerate(re.findall(r"<([0-9a-fA-F]*)>", dst)):
                    table[lo + i] = _u16(d)
            else:
                start = _u16(dst[1:-1])
                for i in range(hi - lo + 1):
                    table[lo + i] = start[:-1] + chr(ord(start[-1]) + i) if start else ""
    return table


# ---------- the PDF's objects, through qpdf ----------

class _Doc:
    def __init__(self, body):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "doc.pdf"
            pdf.write_bytes(body)
            out = subprocess.run(["qpdf", "--json=2", "--json-stream-data=inline", "--decode-level=generalized",
                                  "--json-key=qpdf", "--json-key=pages", str(pdf), "-"], capture_output=True)
        if out.returncode not in (0, 3):  # 3: qpdf succeeded with warnings
            raise ValueError(f"qpdf could not read the PDF: {out.stderr.decode('utf-8', 'replace')[:200]}")
        data = json.loads(out.stdout)
        self.objects, self.pages = data["qpdf"][1], data["pages"]

    def get(self, value):
        """The value of an object, following an indirect reference."""
        if isinstance(value, str) and re.fullmatch(r"\d+ \d+ R", value):
            obj = self.objects.get("obj:" + value, {})
            return obj["value"] if "value" in obj else obj.get("stream", {}).get("dict")
        return value

    def stream(self, ref):
        obj = self.objects["obj:" + ref]["stream"]
        return base64.b64decode(obj.get("data", ""))


class _Font:
    def __init__(self, doc, font):
        self.two_byte = font.get("/Subtype") == "/Type0"
        self.table, self.widths, self.default_width = None, {}, 0
        if font.get("/ToUnicode"):
            self.table = _to_unicode(doc.stream(font["/ToUnicode"]))
        if self.two_byte:
            if font.get("/Encoding") != "/Identity-H":
                raise ValueError(f"unsupported CID font encoding {font.get('/Encoding')}")
            desc = doc.get(doc.get(font["/DescendantFonts"])[0])
            base = desc.get("/BaseFont", "").lstrip("/").split("+")[-1]
            if self.table is None:
                for prefix, cmap in CJK_FONTS.items():
                    if base.startswith(prefix):
                        self.table = cid_table(cmap)
            self.default_width = desc.get("/DW", 1000)
            w = doc.get(desc.get("/W", []))
            i = 0
            while i < len(w):  # [c [w1 w2 ...]] or [c_first c_last w]
                if isinstance(w[i + 1], list):
                    for k, width in enumerate(w[i + 1]):
                        self.widths[w[i] + k] = width
                    i += 2
                else:
                    for c in range(w[i], w[i + 1] + 1):
                        self.widths[c] = w[i + 2]
                    i += 3
        else:
            first = font.get("/FirstChar", 0)
            for k, width in enumerate(doc.get(font.get("/Widths", [])) or []):
                self.widths[first + k] = width
        self.table = self.table or {}

    def codes(self, raw):
        if self.two_byte:
            return [raw[i] << 8 | raw[i + 1] for i in range(0, len(raw) - 1, 2)]
        return list(raw)

    def char(self, code):
        return self.table.get(code, UNKNOWN)

    def width(self, code):
        return self.widths.get(code, self.default_width) / 1000


# ---------- content streams ----------

_TOKEN = re.compile(rb"""
    (?P<ws>[\x00\t\n\x0c\r ]+|%[^\r\n]*)
  | (?P<lit>\()
  | (?P<hex><[0-9A-Fa-f\s]*>)
  | (?P<open><<|\[)
  | (?P<close>>>|\])
  | (?P<name>/[^\x00\t\n\x0c\r ()<>\[\]{}/%]*)
  | (?P<num>[+-]?(?:\d+\.?\d*|\.\d+))
  | (?P<op>[^\x00\t\n\x0c\r ()<>\[\]{}/%]+)
""", re.X)
_ESC = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


def _literal(data, i):
    """A (literal string) starting after its "(" at i: (bytes, index after the closing ")")."""
    out, depth = bytearray(), 1
    while i < len(data):
        c = data[i:i + 1]
        if c == b"\\":
            nxt = data[i + 1:i + 2]
            m = re.match(rb"[0-7]{1,3}", data[i + 1:i + 4])
            if m:
                out.append(int(m.group(), 8) & 0xFF)
                i += 1 + len(m.group())
                continue
            if nxt in (b"\n", b"\r"):  # line continuation
                i += 2 + (nxt == b"\r" and data[i + 2:i + 3] == b"\n")
                continue
            out += _ESC.get(nxt, nxt)
            i += 2
            continue
        if c == b"(":
            depth += 1
        elif c == b")":
            depth -= 1
            if depth == 0:
                return bytes(out), i + 1
        out += c
        i += 1
    raise ValueError("unterminated string in content stream")


def _operations(data):
    """(operator, operands) for each operator of a content stream; inline images are skipped."""
    stack, operands, i = [], [], 0
    while i < len(data):
        m = _TOKEN.match(data, i)
        if not m:
            i += 1
            continue
        kind, tok = m.lastgroup, m.group()
        i = m.end()
        if kind == "ws":
            continue
        if kind == "lit":
            value, i = _literal(data, i)
        elif kind == "hex":
            digits = re.sub(rb"\s", b"", tok[1:-1])
            value = bytes.fromhex((digits + b"0" * (len(digits) % 2)).decode())
        elif kind == "num":
            value = float(tok)
        elif kind == "name":
            value = tok.decode("latin-1")
        elif kind == "open":
            stack.append(operands)
            operands = []
            continue
        elif kind == "close":
            value, operands = operands, stack.pop() if stack else []
        else:
            op = tok.decode("latin-1")
            if op == "BI":  # inline image: skip to its end
                end = re.compile(rb"\sEI(?=[\s]|$)").search(data, data.find(b"ID", i) + 3)
                i = end.end() if end else len(data)
                operands = []
                continue
            if op in ("true", "false", "null"):
                operands.append(op)
                continue
            yield op, operands
            operands = []
            continue
        operands.append(value)


def _mul(a, b):
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3], a[2] * b[0] + a[3] * b[2],
            a[2] * b[1] + a[3] * b[3], a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


def _page_runs(doc, page):
    obj = doc.get(page["object"])
    node, resources = obj, None
    while node is not None and resources is None:  # resources may be inherited
        resources = doc.get(node.get("/Resources"))
        node = doc.get(node.get("/Parent")) if node.get("/Parent") else None
    font_refs = doc.get((resources or {}).get("/Font", {})) or {}
    fonts = {}
    height = doc.get(obj.get("/MediaBox") or [0, 0, 612, 792])[3]
    data = b"\n".join(doc.stream(ref) for ref in page["contents"])

    runs, cur = [], None
    ctm, saved = [1, 0, 0, 1, 0, 0], []
    tm = tlm = [1, 0, 0, 1, 0, 0]
    font = size = None
    tc = tw = rise = 0.0
    th, leading, moved = 1.0, 0.0, True

    def show(strings):
        nonlocal tm, cur, moved
        if font is None:
            raise ValueError("text shown before a font was set")
        trm = _mul([size * th, 0, 0, size, 0, rise], _mul(tm, ctm))
        x, y = trm[4], trm[5]
        scale = math.hypot(trm[2], trm[3])
        text = []
        for item in strings:
            if isinstance(item, float):  # TJ adjustment, thousandths of text space
                tm = _mul([1, 0, 0, 1, -item / 1000 * size * th, 0], tm)
                continue
            for code in font.codes(item):
                ch = font.char(code)
                text.append(ch)
                advance = (font.width(code) * size + tc + (tw if code == 32 and not font.two_byte else 0)) * th
                tm = _mul([1, 0, 0, 1, advance, 0], tm)
        text = "".join(text)
        end = _mul([1, 0, 0, 1, 0, 0], _mul(tm, ctm))[4]
        if moved or cur is None:
            cur = {"left": x, "baseline": y, "size": scale, "text": text, "right": end}
            runs.append(cur)
        else:
            cur["text"] += text
            cur["right"] = end
            cur["size"] = max(cur["size"], scale)
        moved = False

    for op, args in _operations(data):
        if op == "q":
            saved.append(ctm)
        elif op == "Q":
            ctm = saved.pop() if saved else ctm
        elif op == "cm" and len(args) == 6:
            ctm = _mul(args, ctm)
        elif op == "BT":
            tm = tlm = [1, 0, 0, 1, 0, 0]
            moved = True
        elif op == "Tf":
            name, size = args[0], args[1]
            if name not in fonts:
                fonts[name] = _Font(doc, doc.get(font_refs[name]))
            font = fonts[name]
        elif op == "Tc":
            tc = args[0]
        elif op == "Tw":
            tw = args[0]
        elif op == "Tz":
            th = args[0] / 100
        elif op == "TL":
            leading = args[0]
        elif op == "Ts":
            rise = args[0]
        elif op in ("Td", "TD"):
            if op == "TD":
                leading = -args[1]
            tm = tlm = _mul([1, 0, 0, 1, args[0], args[1]], tlm)
            moved = True
        elif op == "Tm":
            tm = tlm = list(args)
            moved = True
        elif op == "T*":
            tm = tlm = _mul([1, 0, 0, 1, 0, -leading], tlm)
            moved = True
        elif op in ("Tj", "TJ"):
            show(args[0] if op == "TJ" else [args[0]])
        elif op in ("'", '"'):
            if op == '"':
                tw, tc = args[0], args[1]
            tm = tlm = _mul([1, 0, 0, 1, 0, -leading], tlm)
            moved = True
            show([args[-1]])
    # top-down coordinates in points, like a page image: top of the run's em box, and its height
    return [{"left": r["left"], "right": r["right"], "top": height - r["baseline"] - 0.88 * r["size"],
             "height": r["size"], "baseline": height - r["baseline"], "text": r["text"]}
            for r in runs if r["text"]]


def runs(body):
    """[[{"left", "right", "top", "height", "baseline", "text"}, ...] per page] in drawing order."""
    doc = _Doc(body)
    return [_page_runs(doc, page) for page in doc.pages]


# ---------- lines ----------

def lines_of(items):
    """Runs joined into printed lines: a run continues the line when it sits on the same baseline
    to the right of the previous run; anything else starts a new line. Runs that touch are joined
    directly; a visible gap (a third of the type size) becomes one space."""
    lines, cur = [], None
    for it in items:
        if cur and abs(it["baseline"] - cur["baseline"]) <= 0.25 * max(it["height"], cur["height"]) \
                and it["left"] >= cur["right"] - 0.6 * it["height"]:  # CJK punctuation is set tight
            gap = it["left"] - cur["right"] > 0.3 * min(it["height"], cur["height"])
            cur["text"] += (" " if gap and not cur["text"].endswith(" ") and not it["text"].startswith(" ")
                            else "") + it["text"]
            cur["right"] = it["right"]
        else:
            cur = dict(it)
            lines.append(cur)
    return [dict(line, text=" ".join(line["text"].split())) for line in lines if line["text"].strip()]


def pdf_text(body):
    """The saved reading of the whole PDF: one printed line per line, pages separated by a blank line."""
    return "\n\n".join("\n".join(line["text"] for line in lines_of(items)) for items in runs(body))


def join_lines(lines):
    """Lines of one paragraph as one string: no space where a CJK character meets a line break."""
    out = ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if out and not (CJK_RE.match(out[-1]) or CJK_RE.match(line[0])):
            out += " "
        out += line
    return out
