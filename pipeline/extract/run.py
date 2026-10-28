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
import tempfile
from pathlib import Path

from ..rawstore import ROOT, RawStore, load_sources
from . import pdf_cid

ELECTION = {"id": "ca-2026-11-03", "name": "November 3, 2026 California General Election", "date": "2026-11-03"}
OUT_DIR = ROOT / "data" / "extracted"
CORRECTIONS_DIR = ROOT / "pipeline" / "corrections"
# Scanned PDFs are read by tesseract 5.5.1 (Homebrew, "eng" model) from pages rendered by poppler's
# pdftoppm at OCR_DPI. Another tesseract version may read a page differently: re-check the OCR'd
# fields against the page images (scripts/ocr_crosscheck.py) after an upgrade.
OCR_DPI = 300
OCR_NOTE = "Text read from a scanned official PDF"


def is_pdf(page):
    return "pdf" in (page["content_type"] or "") or page["body"][:5] == b"%PDF-"


def pdf_text(body, mode="-raw"):
    """Text of a PDF in reading order (poppler's pdftotext -raw), one line per line, single spaces.

    -raw keeps every printed character: the default mode drops hyphens at line ends, which turns
    official words like "non-payment" into "nonpayment". A line ending in "letter-" is joined to the
    next line with no space, so a hyphenated word stays whole and keeps its hyphen."""
    out = subprocess.run(["pdftotext", mode, "-enc", "UTF-8", "-", "-"], input=body, capture_output=True,
                         check=True)
    return tidy_lines(out.stdout.decode("utf-8"))


def tidy_lines(text, join_numbers=False):
    """One line per printed line, single spaces, no blank lines; a word hyphenated at a line end is
    joined to the next line (see pdf_text). With join_numbers, so is a number broken after a hyphen
    ("9-1-" / "1 emergency" -> "9-1-1 emergency"; "535-" / "555 Kelly" -> "535-555 Kelly")."""
    end = r"[A-Za-z0-9]-$" if join_numbers else r"[A-Za-z]-$"
    lines = [" ".join(line.split()) for line in text.split("\n")]
    joined = []
    for line in (line for line in lines if line):
        if joined and re.search(end, joined[-1]) and (line[:1].isalpha() or
                                                      join_numbers and joined[-1][-2:-1].isdigit() and
                                                      line[:1].isdigit()):
            joined[-1] += line
        else:
            joined.append(line)
    return "\n".join(joined)


def pdf_crop_text(body, regions):
    """Text layer of regions of a PDF: [[page, x, y, W, H], ...] in PDF points (72 dpi), each read with
    pdftotext -raw and tidied like pdf_text; regions are joined by a line break. For a page where a
    whole-page reading mixes a question with text beside it (a YES/NO box, a margin note)."""
    texts = []
    for page, x, y, w, h in regions:
        cmd = ["pdftotext", "-raw", "-enc", "UTF-8", "-f", str(page), "-l", str(page), "-x", str(round(x)),
               "-y", str(round(y)), "-W", str(round(w)), "-H", str(round(h)), "-", "-"]
        text = tidy_lines(subprocess.run(cmd, input=body, capture_output=True, check=True).stdout.decode("utf-8"))
        if not text:
            raise ValueError(f"no text in region {[page, x, y, w, h]}")
        texts.append(text)
    return "\n".join(texts)


def pdf_ocr(body, pages, crop=None, dpi=OCR_DPI, psm=None):
    """Text of scanned PDF pages (1-based numbers), read by tesseract and tidied like pdf_text (numbers
    broken at a line-end hyphen are joined too). Each page is rendered by pdftoppm at dpi; with crop
    [x, y, W, H] (PDF points, 72 dpi) only that region of each page is rendered, e.g. the ballot
    question without the YES/NO boxes printed beside its lines. Pages are separated by a blank line."""
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "doc.pdf"
        pdf.write_bytes(body)
        region = []
        if crop:
            x, y, w, h = (round(v * dpi / 72) for v in crop)
            region = ["-x", str(x), "-y", str(y), "-W", str(w), "-H", str(h)]
        texts = []
        for number in pages:
            image = Path(tmp) / f"page{number}"
            subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-f", str(number), "-l", str(number), *region,
                            "-singlefile", str(pdf), str(image)], capture_output=True, check=True)
            cmd = ["tesseract", f"{image}.png", "stdout"] + (["--psm", str(psm)] if psm else [])
            out = subprocess.run(cmd, capture_output=True, check=True)
            text = tidy_lines(out.stdout.decode("utf-8"), join_numbers=True)
            if not text:
                raise ValueError(f"OCR found no text on page {number}")
            texts.append(text)
    return "\n\n".join(texts)


def load_corrections(sid):
    """Reviewed fixes for OCR misreadings: pipeline/corrections/<source>.json, a list of
    {url, ocr, corrected, reason}. Each "ocr" span must occur exactly once in its page's OCR text."""
    path = CORRECTIONS_DIR / f"{sid}.json"
    return json.loads(path.read_text()) if path.exists() else []


def apply_corrections(text, url, corrections):
    """(corrected text, the corrections applied) for one OCR'd PDF."""
    applied = []
    for c in (c for c in corrections if c["url"] == url):
        if text.count(c["ocr"]) != 1:
            raise ValueError(f"correction {c['ocr']!r} does not match the OCR text of {url} exactly once")
        text = text.replace(c["ocr"], c["corrected"])
        applied.append({k: c[k] for k in ("ocr", "corrected", "reason")})
    return text, applied


def main(argv):
    store = RawStore()
    sources = load_sources()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_measures, translations, failures = [], [], 0
    for sid in argv or list(sources):
        src = sources[sid]
        rows = store.latest_pages(sid)
        if not rows:
            print(f"{sid}: nothing in the raw store yet - skipped")
            continue
        pages = {url: dict(row, body=store.read(row["sha256"])) for url, row in rows.items()}
        ocr = src.get("pdf_ocr", {})
        corrections = load_corrections(sid)
        stray = {c["url"] for c in corrections} - set(ocr)
        if stray:
            print(f"{sid}: EXTRACTION FAILED - corrections for PDFs that are not OCR'd: {sorted(stray)}")
            failures += 1
            continue
        for url, page in pages.items():  # PDFs: extract and verify against one saved text version
            if is_pdf(page) and url in ocr:
                # A scanned PDF (no usable text layer): the saved text is tesseract's reading of the listed
                # pages, with any reviewed corrections applied (each one is recorded on its fields).
                spec = ocr[url]
                text = pdf_ocr(page["body"], spec["pages"], spec.get("crop"), spec.get("dpi", OCR_DPI),
                               spec.get("psm"))
                page["text"], page["corrections"] = apply_corrections(text, url, corrections)
                page["text_sha256"] = store.put(page["text"].encode("utf-8"))
                page["ocr"] = True
            elif is_pdf(page) and src.get("pdf_reader") == "content":
                # Read from the content stream by pdf_cid (fonts without Unicode tables, e.g. the Chinese
                # guide); the saved text is that reading.
                page["text"] = pdf_cid.pdf_text(page["body"])
                page["text_sha256"] = store.put(page["text"].encode("utf-8"))
            elif is_pdf(page):
                page["text"] = pdf_text(page["body"])
                saved = page["text"]
                if url in src.get("pdf_second_reading", []):
                    # A few PDFs lose the spaces in some lines under -raw. For those, the layout reading
                    # is saved too, so a field may be cut from (and verified against) either reading.
                    page["layout_text"] = pdf_text(page["body"], "-layout")
                    saved += "\n\n" + page["layout_text"]
                if url in src.get("pdf_crop_reading", {}):
                    # Regions read on their own (e.g. a question beside a YES/NO box), saved the same way.
                    page["crop_text"] = pdf_crop_text(page["body"], src["pdf_crop_reading"][url])
                    saved += "\n\n" + page["crop_text"]
                page["text_sha256"] = store.put(saved.encode("utf-8"))

        def field(text, url, label, _pages=pages):
            row = _pages[url]
            snapshot = row.get("text_sha256") or row["sha256"]
            entry = {"text": text, "source_url": url, "source_label": label,
                     "source_snapshot": str(store.object_path(snapshot).relative_to(ROOT)),
                     "raw_sha256": row["sha256"], "fetched_at": row["fetched_at"],
                     "fetched_by": row["run_kind"]}
            if row.get("ocr"):
                entry["snapshot_kind"] = "pdf-ocr"
                entry["source_note"] = OCR_NOTE
                fixed = [c for c in row["corrections"] if c["corrected"] in text]
                if fixed:
                    entry["corrected"] = fixed
            elif row.get("text_sha256"):
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
        if src.get("translation_of"):  # official translations attach to the measures they translate
            print(f"{sid}: {len(measures)} translated measures from {len(pages)} raw pages")
            translations += measures
            continue
        print(f"{sid}: {len(measures)} measures from {len(pages)} raw pages")
        all_measures += measures
    by_id = {m["id"]: m for m in all_measures}
    for t in translations:
        if t["translation_of"] not in by_id:
            print(f"translation of unknown measure {t['translation_of']} - skipped")
            continue
        by_id[t["translation_of"]].setdefault("translations", {})[t["language"]] = {
            k: v for k, v in t.items() if k not in ("translation_of", "language")}
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
