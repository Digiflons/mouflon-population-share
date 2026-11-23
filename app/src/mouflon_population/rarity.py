"""Rarity of a detected bird (MOUL-47), computed locally on the Pi.

Three independent levels:

- garden: from the bird log. "new" (never logged before), "rare" (heard on fewer
  than N distinct days in the last 12 months) or "regular".
- regional: from the geo model for the home location and this week. "unusual"
  below a probability threshold, otherwise "usual".
- global: the IUCN Red List category, bundled offline from Wikidata (CC0).

Rare birds are also the likeliest false positives, so a rare candidate must be
**confirmed** before it counts: confidence at or above a higher threshold, and
either two such detections within a few minutes or detections by two different
sources. Until then it is "to_confirm" and nothing is written to the bird log.

Each tag carries a short label so a future e-ink frame (MOUL-46) can draw it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from mouflon_population.i18n import t
from mouflon_population.library import THREATENED

if TYPE_CHECKING:
    from datetime import datetime, timedelta


@dataclass(frozen=True)
class Tag:
    level: str
    code: str
    label: str
    short: str
    icon: str
    color: str


GARDEN_STYLE = {
    "new": ("mdi:star-shooting", "green"),
    "rare": ("mdi:star-outline", "teal"),
}


def garden_tag(code: str) -> Tag | None:
    if code not in GARDEN_STYLE:
        return None
    icon, color = GARDEN_STYLE[code]
    return Tag("garden", code, t(f"tag_{code}"), t(f"tag_{code}_short"), icon, color)


def regional_tag() -> Tag:
    return Tag(
        "regional",
        "unusual",
        t("tag_unusual"),
        t("tag_unusual_short"),
        "mdi:map-marker-alert",
        "amber",
    )


IUCN_COLORS = {"NT": "orange", "VU": "deep-orange", "EN": "red", "CR": "purple"}


def iucn_tag(code: str | None) -> Tag | None:
    if code not in THREATENED:
        return None
    return Tag("global", code, t(f"iucn_{code}"), code, "mdi:earth", IUCN_COLORS[code])


def garden_level(first_ever: bool, distinct_days: int, rare_days: int) -> str:
    if first_ever:
        return "new"
    if distinct_days < rare_days:
        return "rare"
    return "regular"


def regional_level(probability: float | None, threshold: float) -> str:
    if probability is None:
        return "unknown"
    return "unusual" if probability < threshold else "usual"


@dataclass
class Rarity:
    garden: str = "regular"
    regional: str = "unknown"
    iucn: str | None = None
    status: str = "none"
    tags: list[Tag] = field(default_factory=list)

    @property
    def is_rare(self) -> bool:
        return bool(self.tags)

    @classmethod
    def from_dict(cls, data: dict) -> Rarity:
        return cls(
            garden=data["garden"],
            regional=data["regional"],
            iucn=data["iucn"],
            status=data["status"],
            tags=[Tag(**t) for t in data["tags"]],
        )

    def as_dict(self) -> dict:
        return {
            "garden": self.garden,
            "regional": self.regional,
            "iucn": self.iucn,
            "status": self.status,
            "tags": [asdict(t) for t in self.tags],
            "labels": [t.label for t in self.tags],
        }


def assess(garden: str, regional: str, iucn: str | None) -> Rarity:
    tags = []
    if (tag := garden_tag(garden)) is not None:
        tags.append(tag)
    if regional == "unusual":
        tags.append(regional_tag())
    if (tag := iucn_tag(iucn)) is not None:
        tags.append(tag)
    return Rarity(garden, regional, iucn, "none", tags)


@dataclass(frozen=True)
class Observation:
    when: datetime
    source: str
    confidence: float


class Confirmer:
    """Holds rare candidates until they are confirmed (rule chosen by the architect)."""

    def __init__(self, min_confidence: float, window: timedelta):
        self.min_confidence = min_confidence
        self.window = window
        self._pending: dict[str, list[Observation]] = defaultdict(list)

    def observe(self, scientific: str, observation: Observation) -> list[Observation]:
        """Observations to log once confirmed, or [] while confirmation runs."""
        pending = [
            o
            for o in self._pending[scientific]
            if observation.when - o.when <= self.window
        ]
        if observation.confidence >= self.min_confidence:
            pending.append(observation)
        self._pending[scientific] = pending
        # Two confident detections within the window; they may come from one source
        # or from two different sources.
        confirmed = len(pending) >= 2
        if confirmed:
            del self._pending[scientific]
            return pending
        return []


@dataclass
class Pending:
    """A bird shown right away as provisional while it is being confirmed (MOUL-53)."""

    scientific: str
    common: str
    rarity: Rarity
    first_seen: datetime
    observations: list[Observation] = field(default_factory=list)


class ConfirmationTracker:
    """Provisional birds and their confirmation progress.

    Steps are generic so later checks (a second model's opinion, local observation
    statistics) can be appended; today there are two: a confident detection and a
    repeat within the window. A bird is confirmed when two detections at or above
    the threshold arrive within the window that starts at its first detection;
    otherwise it is withdrawn when the window ends.
    """

    def __init__(self, min_confidence: float, window: timedelta):
        self.min_confidence = min_confidence
        self.window = window
        self.pending: dict[str, Pending] = {}

    def observe(
        self, scientific: str, common: str, rarity: Rarity, observation: Observation
    ) -> tuple[str, Pending]:
        entry = self.pending.get(scientific)
        if entry is None or observation.when - entry.first_seen > self.window:
            entry = Pending(scientific, common, rarity, observation.when)
            self.pending[scientific] = entry
        entry.observations.append(observation)
        if len(self._confident(entry)) >= 2:
            del self.pending[scientific]
            return "confirmed", entry
        return "provisional", entry

    @property
    def window_minutes(self) -> int:
        return int(self.window.total_seconds() // 60)

    def _confident(self, entry: Pending) -> list[Observation]:
        return [o for o in entry.observations if o.confidence >= self.min_confidence]

    def steps(self, entry: Pending, confirmed: bool = False) -> list[dict]:
        confident = len(self._confident(entry))
        return [
            {
                "name": t("step_confident", threshold=self.min_confidence),
                "done": confirmed or confident >= 1,
            },
            {
                "name": t("step_again", minutes=self.window_minutes),
                "done": confirmed or confident >= 2,
            },
        ]

    def progress(self, entry: Pending, confirmed: bool = False) -> int:
        steps = self.steps(entry, confirmed)
        return round(100 * sum(s["done"] for s in steps) / len(steps))

    def minutes_left(self, entry: Pending, now: datetime) -> int:
        left = entry.first_seen + self.window - now
        return max(0, int(left.total_seconds() // 60))

    def expire(self, now: datetime) -> list[Pending]:
        expired = [e for e in self.pending.values() if now - e.first_seen > self.window]
        for entry in expired:
            del self.pending[entry.scientific]
        return expired
