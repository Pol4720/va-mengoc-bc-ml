"""Generation of LaTeX macro files holding every number quoted in the manuscripts.

Manuscripts never contain hand-typed results: they reference macros such as
``\\PoneNreports``. Values are emitted wrapped in ``siunitx`` commands so that
the decimal marker and digit grouping follow the language of each document
(``\\num{0.35}`` renders as 0.35 in English and 0,35 in Spanish).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["MacroSet"]

_NAME = re.compile(r"^[A-Za-z]+$")
_DIGIT_WORDS = {
    "0": "Zero",
    "1": "One",
    "2": "Two",
    "3": "Three",
    "4": "Four",
    "5": "Five",
    "6": "Six",
    "7": "Seven",
    "8": "Eight",
    "9": "Nine",
}


def macro_name(*parts: str) -> str:
    """Build a letters-only macro name: ``macro_name("P1", "fever_39")`` → ``POneFeverThreeNine``."""
    out = []
    for p in parts:
        for raw_tok in re.split(r"[^A-Za-z0-9]+", p):
            if not raw_tok:
                continue
            tok = "".join(_DIGIT_WORDS.get(ch, ch) for ch in raw_tok)
            out.append(tok[0].upper() + tok[1:])
    return "".join(out)


@dataclass
class MacroSet:
    """Ordered collection of macros for one document family."""

    prefix: str
    suppression_token: str = "<5"  # noqa: S105 - disclosure-control marker, not a secret
    items: dict[str, str] = field(default_factory=dict)
    comments: dict[str, str] = field(default_factory=dict)

    def _put(self, name: str, body: str, comment: str) -> None:
        full = macro_name(self.prefix, name)
        if not _NAME.match(full):  # pragma: no cover - guarded by macro_name
            msg = f"invalid macro name {full}"
            raise ValueError(msg)
        if full in self.items:
            msg = f"duplicate macro {full}"
            raise ValueError(msg)
        self.items[full] = body
        if comment:
            self.comments[full] = comment

    def number(self, name: str, value: float | int | str | None, digits: int = 0, comment: str = "") -> None:
        """A plain number (``\\num``); suppressed or missing values render as a token."""
        self._put(name, self._fmt(value, digits), comment)

    def percent(self, name: str, value: float | None, digits: int = 1, comment: str = "") -> None:
        body = self._fmt(value, digits)
        if body.startswith("\\num"):
            body = body.replace("\\num", "\\qty", 1) + "{\\percent}"
        self._put(name, body, comment)

    def text(self, name: str, value: str, comment: str = "") -> None:
        self._put(name, _escape(value), comment)

    def interval(self, name: str, lo: float | None, hi: float | None, digits: int = 2, comment: str = "") -> None:
        """A confidence interval rendered as ``lo–hi`` with locale-aware numbers."""
        a, b = self._fmt(lo, digits), self._fmt(hi, digits)
        self._put(name, "\\textemdash{}" if a == b == "\\textemdash{}" else f"{a}--{b}", comment)

    def _fmt(self, value: float | int | str | None, digits: int) -> str:
        if value is None:
            return "\\textemdash{}"
        if isinstance(value, str):
            if value == self.suppression_token:
                return "\\ensuremath{<}\\num{" + value.lstrip("<") + "}"
            try:
                v = float(value)
            except ValueError:
                return _escape(value)
        else:
            v = float(value)
        if math.isnan(v):
            return "\\textemdash{}"
        if math.isinf(v):
            return "\\ensuremath{\\infty}"
        if digits == 0:
            return f"\\num{{{round(v):d}}}"
        return f"\\num{{{v:.{digits}f}}}"

    def render(self, header: str) -> str:
        lines = [f"% {header}", "% GENERATED FILE — do not edit by hand (vamengoc release builder).", ""]
        for k, v in self.items.items():
            c = self.comments.get(k)
            if c:
                lines.append(f"% {c}")
            lines.append(f"\\newcommand{{\\{k}}}{{{v}}}")
        return "\n".join(lines) + "\n"

    def write(self, path: Path, header: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render(header), encoding="utf-8")
        return path


def _escape(s: str) -> str:
    rep = {
        "\\": "\\textbackslash{}",
        "&": "\\&",
        "%": "\\%",
        "$": "\\$",
        "#": "\\#",
        "_": "\\_",
        "{": "\\{",
        "}": "\\}",
        "~": "\\textasciitilde{}",
        "^": "\\textasciicircum{}",
    }
    return "".join(rep.get(ch, ch) for ch in s)
