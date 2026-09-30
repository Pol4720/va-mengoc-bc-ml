"""Construction of all dictionary mappers from the project configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vamengoc.config import Project
from vamengoc.normalize.dictionaries import Mapper, split_multi
from vamengoc.parsing.text import compact

__all__ = ["Normalizers", "build_normalizers"]

SITE_SEPARATORS = r"\s*(?:,|;|\+|&|\s+Y\s+)\s*"
ROUTE_SEPARATORS = r"\s*(?:,|;|/|\+|&|\s+Y\s+)\s*"
FREE_TEXT_CATEGORY_SEP = r"\s*(?:,|;|\.|\s+Y\s+)\s*"


@dataclass
class Normalizers:
    vaccine: Mapper
    vaccine_separators: str
    manufacturer: Mapper
    manufacturer_separators: str
    province: Mapper
    place: Mapper
    site: Mapper
    route: Mapper
    destination: Mapper
    destination_separators: str
    other_text_patterns: dict[str, list[str]] = field(default_factory=dict)
    province_region: dict[str, str] = field(default_factory=dict)

    def vaccines(self, value: Any) -> tuple[list[str], list[str]]:
        """Return (codes, unmapped tokens) for a vaccine cell."""
        codes: list[str] = []
        unmapped: list[str] = []
        for tok in split_multi(value, self.vaccine_separators):
            code = self.vaccine.map(tok)
            if code is None:
                unmapped.append(tok)
                code = "X:" + compact(tok)
            codes.append(code)
        return codes, unmapped

    def manufacturers(self, value: Any) -> list[str]:
        out = []
        for tok in split_multi(value, self.manufacturer_separators):
            code = self.manufacturer.map(tok)
            out.append(code or "OTHER")
        return out

    def sites(self, value: Any) -> list[str]:
        return [self.site.map(t) or "OTHER" for t in split_multi(value, SITE_SEPARATORS)]

    def routes(self, value: Any) -> list[str]:
        return [self.route.map(t) or "OTHER" for t in split_multi(value, ROUTE_SEPARATORS)]

    def destinations(self, value: Any) -> list[str]:
        return [self.destination.map(t) or "OTHER" for t in split_multi(value, self.destination_separators)]


def build_normalizers(project: Project) -> Normalizers:
    vac = project.vaccines
    man = project.manufacturers
    geo = project.geography
    ev = project.events
    provinces = geo["provinces"]
    return Normalizers(
        vaccine=Mapper(vac["vaccines"], match_on="text"),
        vaccine_separators=vac["separators"],
        manufacturer=Mapper(
            man["manufacturers"],
            match_on="compact",
            fuzzy_threshold=float(man.get("fuzzy_threshold", 85)),
            default="OTHER",
        ),
        manufacturer_separators=man["separators"],
        province=Mapper(provinces, match_on="text"),
        place=Mapper(geo["places"], match_on="text", default="OTHER"),
        site=Mapper(geo["sites"], match_on="text", default="OTHER"),
        route=Mapper(geo["routes"], match_on="text", default="OTHER"),
        destination=Mapper(geo["destinations"]["map"], match_on="text", default="OTHER"),
        destination_separators=geo["destinations"]["separators"],
        other_text_patterns={k: list(v["patterns"]) for k, v in ev["other_text_categories"].items()},
        province_region={k: v["region"] for k, v in provinces.items()},
    )
