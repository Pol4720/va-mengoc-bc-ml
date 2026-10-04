"""Run provenance and audit trail (ALCOA+: attributable, legible, contemporaneous,
original, accurate — plus complete, consistent, enduring, available).

Each pipeline run records who/what/when: code version (git commit and dirty
state), package and library versions, the SHA-256 of every input file and
configuration file, the random seed, and an append-only log of transformation
steps with row counts. Only metadata is recorded — never row-level values.
"""

from __future__ import annotations

import datetime as dt
import getpass
import json
import platform
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

from vamengoc import __version__
from vamengoc.config import Project, sha256_file

__all__ = ["RunContext", "git_state"]

_TRACKED_PACKAGES = (
    "numpy",
    "pandas",
    "scipy",
    "statsmodels",
    "scikit-learn",
    "lightgbm",
    "ruptures",
    "openpyxl",
    "pyarrow",
    "rapidfuzz",
    "matplotlib",
    "pydantic",
    "cryptography",
)


def git_state(root: Path) -> dict[str, Any]:
    """Current commit and whether the working tree has uncommitted changes."""

    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(  # noqa: S603 - fixed argument list, no shell
                ["git", *args],  # noqa: S607 - git resolved from PATH on purpose
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip()

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain", "--untracked-files=no")  # outputs being built are untracked
    return {
        "commit": commit,
        "dirty": bool(status) if status is not None else None,
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
    }


def _versions() -> dict[str, str]:
    out = {"python": sys.version.split()[0], "vamengoc": __version__}
    for pkg in _TRACKED_PACKAGES:
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = "not installed"
    return out


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


@dataclass
class RunContext:
    """Collects provenance for one pipeline run and persists it on close."""

    project: Project
    command: str
    synthetic: bool
    run_id: str = field(
        default_factory=lambda: dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    )
    started: str = field(default_factory=_now)
    inputs: dict[str, str] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)

    def register_input(self, path: Path) -> str:
        digest = sha256_file(path)
        self.inputs[path.name] = digest
        return digest

    def register_output(self, path: Path) -> None:
        try:
            rel = str(path.relative_to(self.project.root))
        except ValueError:
            rel = str(path)
        self.outputs[rel] = sha256_file(path)

    def step(self, name: str, *, rows_in: int | None = None, rows_out: int | None = None, **details: Any) -> None:
        """Append one transformation step (metadata only)."""
        self.steps.append({"t": _now(), "step": name, "rows_in": rows_in, "rows_out": rows_out, **details})

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    @property
    def run_dir(self) -> Path:
        return self.project.runs_dir / self.run_id

    def manifest(self) -> dict[str, Any]:
        cfg = self.project.config
        return {
            "run_id": self.run_id,
            "command": self.command,
            "data_origin": "synthetic" if self.synthetic else "real",
            "started_utc": self.started,
            "finished_utc": _now(),
            "operator": _safe_user(),
            "host": platform.node(),
            "platform": platform.platform(),
            "git": git_state(self.project.root),
            "versions": _versions(),
            "seed": cfg.analysis.seed,
            "config_sha256": self.project.config_fingerprint(),
            "inputs_sha256": dict(sorted(self.inputs.items())),
            "outputs_sha256": dict(sorted(self.outputs.items())),
            "steps": self.steps,
            "warnings": self.warnings,
        }

    def close(self) -> Path:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        path = self.run_dir / "manifest.json"
        path.write_text(json.dumps(self.manifest(), indent=2, ensure_ascii=False), encoding="utf-8")
        with (self.project.runs_dir / "audit.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "run_id": self.run_id,
                        "command": self.command,
                        "finished_utc": _now(),
                        "n_steps": len(self.steps),
                        "data_origin": "synthetic" if self.synthetic else "real",
                    }
                )
                + "\n"
            )
        return path


def _safe_user() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):  # pragma: no cover - container without passwd entry
        return "unknown"
