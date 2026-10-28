"""Second reading of OCR'd ballot questions by a vision model, as a cross-check only.

    python scripts/ocr_crosscheck.py <source-id> [--env-file PATH] [--only local-sm-r ...] [--probe]

For every field whose text came from tesseract (snapshot_kind "pdf-ocr") in data/extracted/<source>.json,
the PDF pages listed in the source's pdf_ocr are rendered again and sent to a vision model on
OpenRouter, which is asked to transcribe the ballot question. Its answer is compared word by word with
the extracted question and every difference is printed. Nothing here changes the data: a difference is
settled by a person looking at the page image (and, if tesseract is wrong, by a reviewed entry in
pipeline/corrections/). Results, with the model that produced each one, go to
reports/ocr-crosscheck-<source>.json.
"""

import argparse
import base64
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.rawstore import ROOT, RawStore, load_sources  # noqa: E402

API_URL = "https://openrouter.ai/api/v1/chat/completions"
FREE_MODEL = "nvidia/nemotron-3.5-super-vl:free"
PAID_MODEL = "nvidia/nemotron-3.5-super-vl"  # used only after the free model reports its quota is used up
TIMEOUT = 180
IMAGE_DPI = 200  # whole pages, not the OCR crops: the model finds the question on its own
TRIES = 3
PROMPT = ("This is a page of an official document about a local ballot measure. It contains the ballot "
          "question: the text voters will see on the ballot, usually starting with \"Shall\" or \"To\" and "
          "ending with a question mark. Transcribe that question exactly as printed, character for "
          "character, keeping its punctuation, numbers and capitalization. Join lines with single spaces; "
          "leave out YES/NO boxes and anything that is not the question. Output only the question.")


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


class Reader:
    def __init__(self, key):
        self.key, self.model, self.paid_requests = key, FREE_MODEL, 0

    def ask(self, content, label):
        for attempt in range(1, TRIES + 1):
            started = time.monotonic()
            try:
                resp = requests.post(API_URL, timeout=TIMEOUT, headers={"Authorization": f"Bearer {self.key}"},
                                     json={"model": self.model, "temperature": 0,
                                           "messages": [{"role": "user", "content": content}]})
            except requests.RequestException as exc:
                log(f"{label}: {self.model} attempt {attempt} failed: {type(exc).__name__}")
                time.sleep(2 ** attempt)
                continue
            log(f"{label}: {self.model} -> HTTP {resp.status_code} in {time.monotonic() - started:.1f}s")
            if self.model == PAID_MODEL:
                self.paid_requests += 1
            if resp.status_code == 429 and self.model == FREE_MODEL:
                log("free model quota reached: switching to the paid model")
                self.model = PAID_MODEL
                continue
            if resp.status_code >= 500 or resp.status_code == 429:
                time.sleep(2 ** attempt * 5)
                continue
            resp.raise_for_status()
            body = resp.json()
            if "choices" not in body:
                raise RuntimeError(f"{label}: unexpected reply {str(body)[:200]}")
            return body["choices"][0]["message"]["content"] or "", body.get("model", self.model)
        raise RuntimeError(f"{label}: no answer after {TRIES} tries")


def page_images(body, pages):
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "doc.pdf"
        pdf.write_bytes(body)
        for number in pages:
            out = Path(tmp) / f"p{number}"
            subprocess.run(["pdftoppm", "-r", str(IMAGE_DPI), "-png", "-f", str(number), "-l", str(number),
                            "-singlefile", str(pdf), str(out)], check=True, capture_output=True)
            yield number, (Path(f"{out}.png")).read_bytes()


def words(text):
    text = text.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}))
    return re.sub(r"\s+", " ", text).strip().split(" ")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("--env-file", default=str(ROOT / ".env"))
    parser.add_argument("--only", nargs="*", help="measure ids to check")
    parser.add_argument("--probe", action="store_true", help="one tiny text request, then stop")
    args = parser.parse_args()
    load_dotenv(args.env_file)
    key = os.environ.get("OPENROUTER_API_KEY")  # never printed
    if not key:
        sys.exit("OPENROUTER_API_KEY is not set")
    reader = Reader(key)
    if args.probe:
        answer, model = reader.ask([{"type": "text", "text": "Reply with the single word: ready"}], "probe")
        log(f"probe answer from {model}: {answer.strip()[:40]!r}")
        return 0

    src = load_sources()[args.source]
    measures = json.loads((ROOT / "data" / "extracted" / f"{args.source}.json").read_text())
    store = RawStore()
    pages = store.latest_pages(args.source)
    results = []
    for m in measures:
        q = m["fields"].get("ballot_question", {})
        if q.get("snapshot_kind") != "pdf-ocr" or (args.only and m["id"] not in args.only):
            continue
        url = q["source_url"]
        content = [{"type": "text", "text": PROMPT}]
        for number, png in page_images(store.read(pages[url]["sha256"]), src["pdf_ocr"][url]["pages"]):
            content.append({"type": "image_url",
                            "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}})
        answer, model = reader.ask(content, m["id"])
        ours, theirs = words(q["text"]), words(answer)
        diffs = [{"tesseract": " ".join(ours[i1:i2]), "model": " ".join(theirs[j1:j2])}
                 for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ours, theirs, autojunk=False).get_opcodes()
                 if op != "equal"]
        log(f"{m['id']}: {len(diffs)} difference(s) [{model}]")
        for d in diffs:
            print(f"    tesseract: {d['tesseract']!r}\n    model:     {d['model']!r}")
        results.append({"measure": m["id"], "model": model, "source_url": url, "tesseract": q["text"],
                        "model_reading": answer, "differences": diffs})
    out = ROOT / "reports" / f"ocr-crosscheck-{args.source}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"paid_requests": reader.paid_requests, "results": results}, indent=2,
                              ensure_ascii=False) + "\n")
    log(f"{len(results)} question(s) checked, {sum(bool(r['differences']) for r in results)} with differences; "
        f"paid requests: {reader.paid_requests}; written to {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
