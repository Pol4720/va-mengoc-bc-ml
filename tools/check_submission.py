#!/usr/bin/env python3
"""Check journal limits on the compiled PDFs (run after tools/latex_build.py).

* abstract word counts (Drug Safety: up to 450 words when a reporting guideline requires it,
  normally 250; Vaccine: 250);
* Vaccine highlights: 3-5 bullets of at most 85 characters including spaces;
* "authors to complete" markers still present (reported; with --strict they fail).

Counts are made on the rendered text (pdftotext), so they include the generated numbers.
Standard library only; requires poppler-utils (pdftotext).

    python tools/check_submission.py            # report; fail on limit violations
    python tools/check_submission.py --strict   # also fail while markers remain
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "build" / "pdf"

ABSTRACTS = [
    # (pdf, start heading, end heading, word limit)
    ("papers/p1-pharmacovigilance/en/manuscript.pdf", "Abstract", "Introduction", 450),
    ("papers/p2-lot-quality/en/manuscript.pdf", "Abstract", "Introduction", 250),
]
WATERMARKS = ("SYNTHETICDATA", "DATOSSINTÉTICOS", "DATOSSINTETICOS")
HIGHLIGHTS = "submission/p2-lot-quality/highlights.pdf"
PENDING = re.compile(r"\[(?:Authors to complete|A completar por los autores)[^\]]*\]", re.S)
SYNTHETIC_NOTICE = re.compile(r"Synthetic-data build\..*?release/public\.", re.S)


def text(pdf: Path) -> str:
    exe = shutil.which("pdftotext") or "pdftotext"
    out = subprocess.run(  # noqa: S603 - fixed command on a repository file
        [exe, "-enc", "UTF-8", str(pdf), "-"], capture_output=True, text=True, check=True
    )
    return out.stdout


def strip_watermark(t: str) -> str:
    """Remove fragments of the diagonal watermark that pdftotext interleaves with the text."""

    def drop(m: re.Match[str]) -> str:
        run = re.sub(r"\s+", "", m.group(0))
        return " " if any(run in w for w in WATERMARKS) else m.group(0)

    return re.sub(r"(?<![\w])(?:[A-ZÉ]{1,4}\s+)+[A-ZÉ]{1,4}(?![\w])", drop, t)


def heading(t: str, name: str, start: int = 0) -> int:
    """Index of a line that holds only ``name`` (optionally preceded by a section number)."""
    m = re.compile(rf"^\s*(?:\d+\s+)?{re.escape(name)}\s*$", re.M).search(t, start)
    return m.start() if m else -1


def strip_line_numbers(t: str) -> str:
    return "\n".join(re.sub(r"^\s*\d+\s+", "", ln) for ln in t.splitlines())


def words(t: str) -> int:
    return len(re.findall(r"[^\s]+", t))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="fail while 'authors to complete' markers remain")
    args = ap.parse_args()
    if shutil.which("pdftotext") is None:
        print("pdftotext not found", file=sys.stderr)
        return 2
    problems: list[str] = []
    pending_total = 0
    for rel, start, end, limit in ABSTRACTS:
        pdf = PDF / rel
        if not pdf.is_file():
            problems.append(f"{rel}: not built")
            continue
        t = strip_watermark(text(pdf))
        i = heading(t, start)
        j = heading(t, end, i + 1) if i >= 0 else -1
        if i < 0 or j < 0:
            problems.append(f"{rel}: abstract not found")
            continue
        n = words(strip_line_numbers(t[i + len(start) + 1 : j]))
        state = "OK " if n <= limit else "FAIL"
        print(f"[{state}] {rel}: abstract {n} words (limit {limit})")
        if n > limit:
            problems.append(f"{rel}: abstract has {n} words (limit {limit})")
    hl = PDF / HIGHLIGHTS
    if hl.is_file():
        t = strip_watermark(SYNTHETIC_NOTICE.sub("", text(hl)))
        body = t.split("Highlights", 1)[-1]
        bullets = [re.sub(r"\s+", " ", b).strip() for b in re.split(r"\n\s*[•●]\s*", "\n" + body) if b.strip()]
        print(f"[{'OK ' if 3 <= len(bullets) <= 5 else 'FAIL'}] highlights: {len(bullets)} bullets")
        if not 3 <= len(bullets) <= 5:
            problems.append(f"highlights: {len(bullets)} bullets (3-5 required)")
        for b in bullets:
            ok = len(b) <= 85
            print(f"   [{'OK ' if ok else 'FAIL'}] {len(b):3d} chars: {b}")
            if not ok:
                problems.append(f"highlight longer than 85 characters: {b}")
    else:
        problems.append(f"{HIGHLIGHTS}: not built")
    for pdf in sorted(PDF.rglob("*.pdf")):
        n = len(PENDING.findall(re.sub(r"\s+", " ", text(pdf))))
        if n:
            pending_total += n
            print(f"[TODO] {pdf.relative_to(PDF)}: {n} item(s) for the authors to complete")
    if args.strict and pending_total:
        problems.append(f"{pending_total} 'authors to complete' item(s) remain")
    for p in problems:
        print(f"problem: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
