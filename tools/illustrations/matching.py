"""Match Commons plate files to species, beyond the "(illustrations)" categories.

Old plates are often filed under 1900-era synonyms, German names, or only in their
descriptions. A file is matched to a species by, from strongest to weakest:

1. "illustrations" category naming the species or a synonym;
2. structured data "depicts" pointing at the species' Wikidata item;
3. any other category naming the species or a synonym;
4. the scientific name or a synonym in the title or description;
5. a German or English vernacular name (current or historical) in the title or
   description, as a whole phrase.

Weak matches (4 and 5) are flagged for review on the contact sheet.
"""

from __future__ import annotations

import html
import re
import unicodedata

STRENGTH = {
    "illustrations-category": 5,
    "depicts": 4,
    "category": 3,
    "scientific-in-text": 2,
    "vernacular-in-text": 1,
}
WEAK = {"scientific-in-text", "vernacular-in-text"}
# Vernacular names shorter than this are too ambiguous to match in free text.
MIN_VERNACULAR_LENGTH = 5


def normalise(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = unicodedata.normalize("NFKD", text.replace("ß", "ss"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def is_binomial(name: str) -> bool:
    return len(name.split()) >= 2


def phrase_pattern(phrases: list[str]) -> re.Pattern | None:
    """One regex matching any of the (normalised) phrases as whole words."""
    if not phrases:
        return None
    ordered = sorted(set(phrases), key=len, reverse=True)
    body = "|".join(re.escape(p) for p in ordered)
    return re.compile(rf"(?<![a-z])(?:{body})(?![a-z])")


class Index:
    """Looks up which species a file shows."""

    def __init__(self, taxa: dict[str, dict]):
        self.by_name: dict[str, str] = {}
        self.by_item: dict[str, str] = {}
        self.by_vernacular: dict[str, str] = {}
        for scientific, taxon in taxa.items():
            for name in taxon.get("names", []):
                if is_binomial(name):
                    self.by_name.setdefault(normalise(name), scientific)
            for item in taxon.get("items", []) or [taxon.get("wikidata")]:
                if item:
                    self.by_item.setdefault(item, scientific)
            for name in taxon.get("vernacular", []):
                key = normalise(name)
                if len(key) >= MIN_VERNACULAR_LENGTH:
                    self.by_vernacular.setdefault(key, scientific)
        self._names = phrase_pattern(list(self.by_name))
        self._vernacular = phrase_pattern(list(self.by_vernacular))

    @staticmethod
    def _find(pattern, table, text: str) -> set[str]:
        if pattern is None:
            return set()
        return {table[m] for m in pattern.findall(normalise(text))}

    def names_in(self, text: str) -> set[str]:
        return self._find(self._names, self.by_name, text)

    def vernacular_in(self, text: str) -> set[str]:
        return self._find(self._vernacular, self.by_vernacular, text)

    def matches(self, meta: dict, depicts: list[str] = ()) -> dict[str, str]:
        """{species: strongest match kind} for one file."""
        result: dict[str, str] = {}

        def add(scientific: str, kind: str) -> None:
            if STRENGTH[kind] > STRENGTH.get(result.get(scientific, ""), 0):
                result[scientific] = kind

        for category in meta.get("categories", []):
            label = category.removeprefix("Category:")
            kind = (
                "illustrations-category"
                if "illustration" in label.lower()
                else "category"
            )
            for scientific in self.names_in(label):
                add(scientific, kind)
        for item in depicts:
            if item in self.by_item:
                add(self.by_item[item], "depicts")
        text = f"{meta.get('title', '')} {meta.get('description') or ''}"
        for scientific in self.names_in(text):
            add(scientific, "scientific-in-text")
        for scientific in self.vernacular_in(text):
            add(scientific, "vernacular-in-text")
        return result
