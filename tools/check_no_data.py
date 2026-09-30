#!/usr/bin/env python3
"""Repository guard: refuse restricted data, secrets and oversized files in git.

Run by pre-commit on staged files and by CI on the whole tree
(``python tools/check_no_data.py --all``). Exit status 1 on any violation.
Standard library only, so it runs before the environment is installed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_SUFFIXES = {
    ".xlsx",
    ".xlsm",
    ".xls",
    ".xlsb",
    ".ods",
    ".sav",
    ".dta",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".duckdb",
    ".parquet",
    ".feather",
    ".pkl",
    ".pickle",
    ".joblib",
    ".key",
    ".pem",
    ".enc",
}
FORBIDDEN_PREFIXES = ("data/raw/", "data/interim/", "data/curated/", "data/synthetic/", "runs/", "secrets/")
ALLOWED_IN_DATA = {"data/README.md"}
MAX_BYTES = 5 * 1024 * 1024
MAX_BYTES_RELEASE = 25 * 1024 * 1024
CONTENT_PATTERNS = [
    (re.compile(r"(?i)nombres?\s+y\s+apellidos\s*[,;\t]"), "AEFI header row (names) in a data-like file"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)VAMENGOC_(HMAC|FERNET)_KEY\s*=\s*['\"]?[0-9a-zA-Z+/=]{32,}"), "secret key value"),
]
TEXT_SUFFIXES = {
    ".csv",
    ".tsv",
    ".txt",
    ".json",
    ".md",
    ".tex",
    ".py",
    ".yaml",
    ".yml",
    ".toml",
    ".ts",
    ".tsx",
    ".js",
    ".html",
    ".css",
}
SELF = "tools/check_no_data.py"


def tracked_files(all_files: bool, paths: list[str]) -> list[str]:
    if paths:
        return paths
    cmd = ["git", "ls-files"] if all_files else ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)  # noqa: S603
    return [line for line in out.stdout.splitlines() if line]


def check(files: list[str]) -> list[str]:
    errors: list[str] = []
    for f in files:
        p = Path(f)
        norm = f.replace("\\", "/")
        if not p.is_file():
            continue
        if norm.startswith(FORBIDDEN_PREFIXES) and not norm.endswith(".gitkeep") and norm not in ALLOWED_IN_DATA:
            errors.append(f"{f}: restricted directory (data tiers and run artefacts are never versioned)")
        if p.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f"{f}: file type {p.suffix} may contain restricted data or secrets")
        limit = MAX_BYTES_RELEASE if norm.startswith("release/") else MAX_BYTES
        if p.stat().st_size > limit:
            errors.append(f"{f}: larger than {limit // (1024 * 1024)} MB")
        if p.suffix.lower() in TEXT_SUFFIXES and norm != SELF and not norm.startswith("tests/"):
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for rx, why in CONTENT_PATTERNS:
                if rx.search(text):
                    errors.append(f"{f}: {why}")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="check every tracked file instead of the staged ones")
    ap.add_argument("paths", nargs="*")
    args = ap.parse_args()
    errors = check(tracked_files(args.all, args.paths))
    for e in errors:
        print(f"[data-guard] {e}", file=sys.stderr)
    if errors:
        print(f"[data-guard] {len(errors)} problem(s). See docs/DATA_GOVERNANCE.md.", file=sys.stderr)
        return 1
    print("[data-guard] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
