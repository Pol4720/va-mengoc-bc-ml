#!/usr/bin/env python3
"""Build LaTeX documents and fail on ANY diagnostic.

Policy: 0 errors, 0 warnings, 0 overfull/underfull boxes, 0 undefined
references or citations, 0 BibTeX warnings — in every document and language.

Documents are listed in ``tools/latex_documents.txt`` (one path per line,
relative to the repository root). Each is compiled with ``latexmk`` into
``build/latex/<doc path>/`` and the resulting PDF is copied next to that build
tree under ``build/pdf/``. Standard library only.

    python tools/latex_build.py            # every listed document
    python tools/latex_build.py papers/p1-pharmacovigilance/en/manuscript.tex
    python tools/latex_build.py --json build/latex-report.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_LIST = ROOT / "tools" / "latex_documents.txt"
BUILD = ROOT / "build"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("error", re.compile(r"^(?:\S+:\d+: |! )(.+)$")),
    ("overfull", re.compile(r"^(Overfull \\[hv]box .*)$")),
    ("underfull", re.compile(r"^(Underfull \\[hv]box .*)$")),
    ("undefined_citation", re.compile(r"(Citation `[^']+' .*undefined.*)")),
    ("undefined_reference", re.compile(r"(Reference `[^']+' .*undefined.*)")),
    ("warning", re.compile(r"^((?:LaTeX|Package|Class|pdfTeX|LaTeX Font|Font)\b.*Warning.*)$")),
    ("warning", re.compile(r"^(.*There were (?:undefined|multiply-defined) (?:references|labels).*)$")),
]
BLG_WARNING = re.compile(r"^(Warning--.*|WARN - .*)$")
# Informational messages that are not defects. Deliberately empty: every warning is treated as a defect.
IGNORE: list[re.Pattern[str]] = []


@dataclass
class Result:
    document: str
    ok: bool = False
    pdf: str | None = None
    pages: int | None = None
    diagnostics: list[dict[str, str]] = field(default_factory=list)
    failure: str = ""


def documents(args: list[str]) -> list[Path]:
    if args:
        return [ROOT / a for a in args]
    lines = [ln.strip() for ln in DOC_LIST.read_text(encoding="utf-8").splitlines()]
    return [ROOT / ln for ln in lines if ln and not ln.startswith("#")]


def _join_wrapped(log: str) -> list[str]:
    """TeX wraps log lines at 79 characters; re-join them for reliable matching."""
    out: list[str] = []
    buf = ""
    for line in log.splitlines():
        buf += line
        if len(line) != 79:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def parse_log(log_text: str) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for line in _join_wrapped(log_text):
        if any(p.search(line) for p in IGNORE):
            continue
        for kind, rx in PATTERNS:
            m = rx.search(line)
            if m:
                found.append({"kind": kind, "message": m.group(1)[:300]})
                break
    return found


def build(tex: Path, timeout: int = 900) -> Result:
    rel = tex.relative_to(ROOT)
    res = Result(document=str(rel))
    if not tex.is_file():
        res.failure = "file not found"
        return res
    out_dir = BUILD / "latex" / rel.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "latexmk",
        "-pdf",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        f"-outdir={out_dir}",
        "-quiet",
        tex.name,
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed latexmk command, no shell
            cmd,
            cwd=tex.parent,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
            check=False,
        )
    except subprocess.TimeoutExpired:
        res.failure = "timeout"
        return res
    log_path = out_dir / (tex.stem + ".log")
    log = log_path.read_text(encoding="latin-1", errors="replace") if log_path.is_file() else ""
    res.diagnostics = parse_log(log)
    blg = out_dir / (tex.stem + ".blg")
    if blg.is_file():
        for line in blg.read_text(encoding="latin-1", errors="replace").splitlines():
            if BLG_WARNING.match(line):
                res.diagnostics.append({"kind": "bibtex", "message": line[:300]})
    pdf = out_dir / (tex.stem + ".pdf")
    if proc.returncode != 0 and not res.diagnostics:
        res.diagnostics.append({"kind": "error", "message": (proc.stdout + proc.stderr)[-600:]})
    if pdf.is_file():
        target = BUILD / "pdf" / rel.with_suffix(".pdf")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pdf, target)
        res.pdf = str(target.relative_to(ROOT))
        m = re.search(r"Output written on .*\((\d+) pages?", log)
        res.pages = int(m.group(1)) if m else None
    res.ok = proc.returncode == 0 and not res.diagnostics and pdf.is_file()
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("docs", nargs="*", help="documents (default: tools/latex_documents.txt)")
    ap.add_argument("--json", type=Path, help="write a JSON report")
    args = ap.parse_args()
    if shutil.which("latexmk") is None:
        print("latexmk not found", file=sys.stderr)
        return 2
    results = [build(d) for d in documents(args.docs)]
    for r in results:
        state = "OK " if r.ok else "FAIL"
        print(f"[{state}] {r.document}  pages={r.pages}  diagnostics={len(r.diagnostics)}  {r.failure}")
        for d in r.diagnostics[:40]:
            print(f"        {d['kind']}: {d['message']}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
    bad = [r for r in results if not r.ok]
    print(f"{len(results) - len(bad)}/{len(results)} documents clean.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
