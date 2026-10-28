"""PDF readings in pipeline/extract/run.py (OCR, crop readings, corrections) and how seed.py verifies
OCR'd fields, with the external tools (pdftoppm, pdftotext, tesseract) replaced by stubs."""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.extract import run


class Tools:
    """Stands in for subprocess.run: records each command and answers tesseract / pdftotext."""

    def __init__(self, output):
        self.calls, self.output = [], output

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if cmd[0] == "pdftoppm":
            Path(cmd[-1] + ".png").write_bytes(b"png")
        return SimpleNamespace(stdout=self.output.encode("utf-8") if cmd[0] != "pdftoppm" else b"")


def test_ocr_renders_the_crop_and_tidies_the_text(monkeypatch):
    tools = Tools("Shall the measure providing rapid response to 9-1-\n1 emergency calls at 535-\n555 Kelly\n\n"
                  "Avenue for single-\nfamily homes?\n")
    monkeypatch.setattr(subprocess, "run", tools)
    text = run.pdf_ocr(b"%PDF-", [2], crop=[72, 144, 360, 36], dpi=300, psm=6)
    assert text == ("Shall the measure providing rapid response to 9-1-1 emergency calls at 535-555 Kelly\n"
                    "Avenue for single-family homes?")
    render, read = tools.calls
    assert render[:8] == ["pdftoppm", "-r", "300", "-png", "-f", "2", "-l", "2"]
    assert render[8:16] == ["-x", "300", "-y", "600", "-W", "1500", "-H", "150"]  # points -> 300 dpi pixels
    assert read[0] == "tesseract" and read[-2:] == ["--psm", "6"]


def test_ocr_of_a_blank_page_fails(monkeypatch):
    monkeypatch.setattr(subprocess, "run", Tools("  \n"))
    with pytest.raises(ValueError):
        run.pdf_ocr(b"%PDF-", [1])


def test_text_readings_keep_numbers_apart():
    # pdf_text's tidying is unchanged: only OCR joins numbers broken at a hyphen
    assert run.tidy_lines("from 2025-\n2026 non-\npayment") == "from 2025-\n2026 non-payment"


def test_crop_reading_reads_each_region(monkeypatch):
    tools = Tools("Shall the measure\nbe adopted?\n")
    monkeypatch.setattr(subprocess, "run", tools)
    assert run.pdf_crop_text(b"%PDF-", [[2, 87.1, 103, 330, 63.5], [3, 0, 0, 10, 10]]) == \
        "Shall the measure\nbe adopted?\nShall the measure\nbe adopted?"
    assert tools.calls[0][:14] == ["pdftotext", "-raw", "-enc", "UTF-8", "-f", "2", "-l", "2",
                                   "-x", "87", "-y", "103", "-W", "330"]


def test_corrections_apply_once_and_are_listed():
    fixes = [{"url": "u", "ocr": "Cafiada", "corrected": "Cañada", "reason": "tesseract misreads ñ"},
             {"url": "other", "ocr": "x", "corrected": "y", "reason": "-"}]
    text, applied = run.apply_corrections("College of San Mateo, Cafiada College", "u", fixes)
    assert text == "College of San Mateo, Cañada College"
    assert applied == [{"ocr": "Cafiada", "corrected": "Cañada", "reason": "tesseract misreads ñ"}]
    with pytest.raises(ValueError):  # a correction must match the OCR text exactly once
        run.apply_corrections("no match here", "u", fixes)


def _seed():
    spec = importlib.util.spec_from_file_location("seed", Path(__file__).resolve().parent.parent / "scripts" / "seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_verifies_ocr_fields_against_the_saved_reading(tmp_path, monkeypatch):
    seed = _seed()
    monkeypatch.setattr(seed.config, "ROOT", tmp_path)
    (tmp_path / "ocr.txt").write_text("Shall <the> measure be adopted?")
    entry = {"text": "x", "source_url": "https://example.org/a.pdf", "source_snapshot": "ocr.txt",
             "snapshot_kind": "pdf-ocr", "fetched_by": "crawl"}
    # read from the snapshot even with --live (no network), and never treated as HTML
    assert seed.page_text(entry, {}, live=True) == "Shall <the> measure be adopted?"
