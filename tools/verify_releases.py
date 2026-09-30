#!/usr/bin/env python3
"""Verify every committed release directory (release/public, release/synthetic).

Exit status 1 if any release fails the disclosure-control guard. Used by the
pre-commit hook and by CI.
"""

from __future__ import annotations

import sys

from vamengoc.config import Project
from vamengoc.release.verify import verify_release


def main() -> int:
    project = Project()
    status = 0
    found = False
    for origin in ("public", "synthetic"):
        root = project.release_dir / origin
        if not root.is_dir():
            continue
        found = True
        rep = verify_release(project, root)
        if rep.ok:
            print(f"[release-verify] {origin}: OK ({rep.checked_files} files)")
        else:
            status = 1
            print(f"[release-verify] {origin}: {len(rep.errors)} problem(s)", file=sys.stderr)
            for e in rep.errors[:100]:
                print(f"  - {e}", file=sys.stderr)
    if not found:
        print("[release-verify] no release directory present")
    return status


if __name__ == "__main__":
    sys.exit(main())
