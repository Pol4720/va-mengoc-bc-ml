"""Dictionary-driven normalisation of free-text categorical values.

Mapping rules live in versioned YAML files (``configs/dictionaries``). A
:class:`Mapper` applies, in order: exact regex patterns over the normalised
token, an optional fuzzy match against anchor strings, and finally a default
code. Every distinct input value and the rule that mapped it are recorded in
a :class:`MappingLog`, which is exported (as counts only) with the data-quality
report so reviewers can audit the harmonisation.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz, process

from vamengoc.parsing.text import MISSING_TOKENS, cell_to_str, compact, normalize_text, strip_accents

__all__ = ["Mapper", "MappingLog", "split_multi"]


@dataclass
class MappingLog:
    """Counts of (input token → code, rule) decisions."""

    decisions: Counter[tuple[str, str, str]] = field(default_factory=Counter)

    def add(self, token: str, code: str | None, rule: str) -> None:
        self.decisions[(token, code or "<none>", rule)] += 1

    def summary(self) -> dict[str, Any]:
        by_rule: Counter[str] = Counter()
        by_code: dict[str, Counter[str]] = defaultdict(Counter)
        for (_tok, code, rule), n in self.decisions.items():
            by_rule[rule] += n
            by_code[code][rule] += n
        return {
            "n_values": sum(self.decisions.values()),
            "n_distinct_inputs": len({t for t, _, _ in self.decisions}),
            "by_rule": dict(by_rule),
            "by_code": {k: dict(v) for k, v in sorted(by_code.items())},
        }

    def table(self) -> list[dict[str, Any]]:
        """Full decision table — LOCAL USE ONLY (input tokens may be free text)."""
        return [
            {"input": t, "code": c, "rule": r, "n": n}
            for (t, c, r), n in sorted(self.decisions.items(), key=lambda kv: -kv[1])
        ]


def split_multi(value: Any, separators: str) -> list[str]:
    """Split a multi-valued cell on the configured separators.

    Splitting happens on the accent-stripped, upper-cased text *before*
    punctuation is removed, so separators such as ``,`` and ``+`` survive.
    """
    text = cell_to_str(value)
    if text is None:
        return []
    text = strip_accents(text).upper().strip()
    if normalize_text(text) in MISSING_TOKENS:
        return []
    return [p.strip() for p in re.split(separators, text) if p and p.strip()]


class Mapper:
    """Map raw tokens to canonical codes.

    Parameters
    ----------
    entries:
        ``{code: {"patterns": [...], "fuzzy_anchors": [...]}}``.
    match_on:
        ``"text"`` compares against :func:`normalize_text`; ``"compact"`` strips spaces too.
    fuzzy_threshold:
        Minimum rapidfuzz ``ratio`` for the fuzzy fallback (``None`` disables it).
    default:
        Code for non-missing values that match nothing (``None`` keeps them unmapped).
    """

    def __init__(
        self,
        entries: dict[str, dict[str, Any]],
        *,
        match_on: str = "text",
        fuzzy_threshold: float | None = None,
        default: str | None = None,
    ) -> None:
        self.match_on = match_on
        self.fuzzy_threshold = fuzzy_threshold
        self.default = default
        self.log = MappingLog()
        self._rules: list[tuple[re.Pattern[str], str]] = []
        self._anchors: dict[str, str] = {}
        for code, spec in entries.items():
            for pat in spec.get("patterns", []) or []:
                self._rules.append((re.compile(rf"^(?:{pat})$"), code))
            for anchor in spec.get("fuzzy_anchors", []) or []:
                self._anchors[compact(anchor)] = code
        self._cache: dict[str, tuple[str | None, str]] = {}

    def _key(self, value: Any) -> str:
        return compact(value) if self.match_on == "compact" else normalize_text(value)

    def map(self, value: Any) -> str | None:
        key = self._key(value)
        if key in self._cache:
            code, rule = self._cache[key]
            self.log.add(key, code, rule)
            return code
        code, rule = self._resolve(key)
        self._cache[key] = (code, rule)
        self.log.add(key, code, rule)
        return code

    def _resolve(self, key: str) -> tuple[str | None, str]:
        if normalize_text(key) in MISSING_TOKENS:
            # An explicit rule (e.g. manufacturer "N" -> UNKNOWN) still wins.
            for pattern, code in self._rules:
                if pattern.match(key):
                    return code, "pattern"
            return None, "missing"
        for pattern, code in self._rules:
            if pattern.match(key):
                return code, "pattern"
        if self.fuzzy_threshold is not None and self._anchors:
            hit = process.extractOne(compact(key), list(self._anchors), scorer=fuzz.ratio)
            if hit is not None and hit[1] >= self.fuzzy_threshold:
                return self._anchors[hit[0]], f"fuzzy:{round(hit[1])}"
        if self.default is not None:
            return self.default, "default"
        return None, "unmapped"
