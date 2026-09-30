#!/usr/bin/env python3
"""Generate BibTeX entries from PubMed metadata (NCBI E-utilities, efetch XML).

Every journal article cited in the manuscripts is listed in
``papers/shared/bib/pubmed.tsv`` as ``<bibkey><TAB><PMID>``. This script fetches the
authoritative record for each PMID and writes ``papers/shared/bib/pubmed.bib``, so
author lists, volumes, pages and DOIs are never typed by hand. References without a
PMID (books, standards, software, legislation) live in ``manual.bib``.

Only public bibliographic identifiers are sent to NCBI; no study data are involved.
Standard library only.

    python tools/bib_pubmed.py            # regenerate pubmed.bib
    python tools/bib_pubmed.py --check    # fail if pubmed.bib is stale
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIB_DIR = ROOT / "papers" / "shared" / "bib"
TSV = BIB_DIR / "pubmed.tsv"
OUT = BIB_DIR / "pubmed.bib"
CACHE = BIB_DIR / "pubmed.cache.json"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

# Characters that must be escaped or converted for 8-bit BibTeX.
TEX_MAP = {
    "&": r"\&",
    "%": r"\%",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "–": "--",
    "—": "---",
    "‘": "`",
    "’": "'",
    "“": "``",
    "”": "''",
    " ": "~",
    " ": r"\,",
    "±": r"$\pm$",
    "≤": r"$\leq$",
    "≥": r"$\geq$",
    "®": r"\textsuperscript{\textregistered}",
    "™": r"\texttrademark{}",
    "º": r"\textsuperscript{o}",
    "×": r"$\times$",
    "α": r"$\alpha$",
    "β": r"$\beta$",
}
ACCENTS = {
    "\u0301": "'",
    "\u0300": "`",
    "\u0302": "^",
    "\u0308": '"',
    "\u0303": "~",
    "\u0307": ".",
    "\u0304": "=",
    "\u0327": "c",
    "\u030c": "v",
    "\u0306": "u",
    "\u030b": "H",
    "\u0328": "k",
    "\u030a": "r",
}
SPECIAL_LETTERS = {
    "ø": r"{\o}",
    "Ø": r"{\O}",
    "å": r"{\aa}",
    "Å": r"{\AA}",
    "æ": r"{\ae}",
    "Æ": r"{\AE}",
    "ß": r"{\ss}",
}


def tex(text: str) -> str:
    """Convert Unicode text to BibTeX-safe LaTeX (accents as braced commands)."""
    out: list[str] = []
    for ch in text:
        if ch in SPECIAL_LETTERS:
            out.append(SPECIAL_LETTERS[ch])
            continue
        if ch in TEX_MAP:
            out.append(TEX_MAP[ch])
            continue
        if ord(ch) < 128:
            out.append(ch)
            continue
        decomposed = unicodedata.normalize("NFD", ch)
        base, marks = decomposed[0], decomposed[1:]
        if len(marks) == 1 and marks in ACCENTS and ord(base) < 128:
            cmd = ACCENTS[marks]
            base_tex = r"\i" if base == "i" else base
            out.append(f"{{\\{cmd}{{{base_tex}}}}}" if cmd.isalpha() else f"{{\\{cmd}{base_tex}}}")
            continue
        raise ValueError(f"no LaTeX mapping for character {ch!r} (U+{ord(ch):04X}) in {text!r}")
    return "".join(out)


def protect_title(title: str) -> str:
    """Brace words that must keep their capitalisation (acronyms, proper nouns, mixed case)."""
    words = title.split(" ")
    protected = []
    for i, w in enumerate(words):
        core = w.strip(".,:;()[]'\"?")
        needs = (
            sum(c.isupper() for c in core) >= 2
            or (any(c.isdigit() for c in core) and any(c.isalpha() for c in core))
            or (i > 0 and core[:1].isupper() and core.lower() not in STOP_CAPS)
        )
        protected.append("{" + w + "}" if needs and "{" not in w and "\\" not in w and "$" not in w else w)
    return " ".join(protected)


STOP_CAPS = {"a", "an", "the", "and", "of", "in", "on", "for", "to", "with", "by", "from", "at", "or"}


HEAVY = (
    "Abstract",
    "OtherAbstract",
    "MeshHeadingList",
    "ReferenceList",
    "KeywordList",
    "ChemicalList",
    "CommentsCorrectionsList",
    "GrantList",
    "History",
    "AffiliationInfo",
    "Identifier",
    "PublicationTypeList",
)


def _strip_heavy(node: ET.Element) -> None:
    """Keep the cache small: drop abstracts, MeSH, references and affiliations."""
    for child in list(node):
        if child.tag in HEAVY:
            node.remove(child)
        else:
            _strip_heavy(child)


def fetch(pmids: list[str]) -> dict[str, str]:
    """Return {pmid: PubmedArticle XML string}, using a local cache to avoid needless requests."""
    cache: dict[str, str] = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.is_file() else {}
    missing = [p for p in pmids if p not in cache]
    for i in range(0, len(missing), 100):
        chunk = missing[i : i + 100]
        url = EFETCH + "?" + urllib.parse.urlencode({"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
                    root = ET.fromstring(resp.read())  # noqa: S314
                break
            except OSError:
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
        for art in root.findall("PubmedArticle"):
            pmid = art.findtext("MedlineCitation/PMID") or ""
            _strip_heavy(art)
            cache[pmid] = ET.tostring(art, encoding="unicode")
        time.sleep(0.4)
    CACHE.write_text(json.dumps(cache, indent=0, sort_keys=True), encoding="utf-8")
    return cache


def _text(node: ET.Element | None) -> str:
    return "".join(node.itertext()).strip() if node is not None else ""


def entry(key: str, pmid: str, xml: str) -> str:
    art = ET.fromstring(xml)  # noqa: S314
    a = art.find("MedlineCitation/Article")
    if a is None:
        raise ValueError(f"PMID {pmid}: no Article element")
    authors: list[str] = []
    for au in a.findall("AuthorList/Author"):
        last, fore = au.findtext("LastName"), au.findtext("ForeName") or au.findtext("Initials") or ""
        coll = au.findtext("CollectiveName")
        if last:
            authors.append(f"{tex(last)}, {tex(fore)}".strip(", "))
        elif coll:
            authors.append("{" + tex(coll) + "}")
    journal = a.find("Journal")
    issue = journal.find("JournalIssue") if journal is not None else None
    year = (issue.findtext("PubDate/Year") if issue is not None else None) or (
        (issue.findtext("PubDate/MedlineDate") or "")[:4] if issue is not None else ""
    )
    title = _text(a.find("ArticleTitle")).rstrip(".")
    title = re.sub(r"(?<=\d)-(?=\d)", "\u2013", title)  # numeric ranges take an en dash
    title = re.sub(r"\s+:", ":", title)
    title = re.sub(r"(?<=[A-Za-z]):(?=\d)", ": ", title)
    fields: dict[str, str] = {
        "author": " and ".join(authors),
        "title": "{" + protect_title(tex(title)) + "}",
        "journal": tex(journal.findtext("ISOAbbreviation") or journal.findtext("Title") or "") if journal else "",
        "year": year,
        "volume": (issue.findtext("Volume") or "") if issue is not None else "",
        "number": (issue.findtext("Issue") or "") if issue is not None else "",
        "pages": (a.findtext("Pagination/MedlinePgn") or "").replace("-", "--"),
        "pmid": pmid,
    }
    if not fields["pages"]:
        eloc = a.find("ELocationID[@EIdType='pii']")
        fields["pages"] = eloc.text if eloc is not None and eloc.text else ""
    doi = next(
        (x.text for x in art.findall("PubmedData/ArticleIdList/ArticleId") if x.get("IdType") == "doi" and x.text),
        "",
    ) or next((x.text for x in a.findall("ELocationID") if x.get("EIdType") == "doi" and x.text), "")
    if doi:
        fields["doi"] = doi
    body = ",\n".join(f"  {k:<8}= {{{v}}}" if k != "title" else f"  {k:<8}= {v}" for k, v in fields.items() if v)
    return f"@article{{{key},\n{body}\n}}\n"


def read_tsv() -> list[tuple[str, str]]:
    rows = []
    for raw in TSV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, pmid = line.split("\t")[:2]
        rows.append((key.strip(), pmid.strip()))
    keys = [k for k, _ in rows]
    dup = {k for k in keys if keys.count(k) > 1}
    if dup:
        raise SystemExit(f"duplicate keys in {TSV}: {sorted(dup)}")
    return rows


def render() -> str:
    rows = read_tsv()
    records = fetch([p for _, p in rows])
    header = (
        "% GENERATED FILE — do not edit by hand.\n"
        "% Source: PubMed (NCBI E-utilities efetch) via tools/bib_pubmed.py from pubmed.tsv.\n\n"
    )
    return header + "\n".join(entry(k, p, records[p]) for k, p in rows)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if pubmed.bib differs from a fresh render")
    args = ap.parse_args()
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != text:
            print("pubmed.bib is stale: run python tools/bib_pubmed.py", file=sys.stderr)
            return 1
        print("pubmed.bib up to date")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({text.count('@article')} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
