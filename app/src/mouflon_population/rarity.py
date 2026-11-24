"""Rarity of a detected bird (MOUL-47), computed locally on the Pi.

Three independent levels:

- garden: from the bird log. "new" (never logged before), "rare" (heard on fewer
  than N distinct days in the last 12 months) or "regular".
- regional: from the geo model for the home location and this week. "unusual"
  below a probability threshold, otherwise "usual".
- global: the IUCN Red List category, bundled offline from Wikidata (CC0).

Rare birds are also the likeliest false positives, so a rare or uncertain candidate
must be **confirmed** before it counts (see :class:`ConfirmationTracker`: two of
four checks). Until then it is "provisional" and nothing is written to the bird log.

Each tag carries a short label so a future e-ink frame (MOUL-46) can draw it.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from mouflon_population.i18n import has_text, t
from mouflon_population.library import THREATENED

if TYPE_CHECKING:
    from collections.abc import Callable
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
    # Cross-checks (MOUL-54, MOUL-55): "agree" / "disagree" / "skipped:<reason>" for
    # Perch, "observed" / "rare" / "skipped:<reason>" for the local statistics.
    perch: str = "skipped:not_needed"
    local: str = "skipped:unavailable"
    # How many checks confirm it: 2 normally, 3 for a bird rescued by the silent
    # check (Perch and the local check got it in; one more check confirms it).
    required: int = 2
    # A sure, common bird: confirmed only once heard again (owner's decision).
    needs_repeat: bool = False


STEP_KEYS = ("confident", "again", "perch", "local")
REQUIRED_STEPS = 2


class ConfirmationTracker:
    """Provisional birds and their confirmation progress (MOUL-53, MOUL-54, MOUL-55).

    Up to four checks, each "done", "pending", "failed" or "skipped":

    1. confident: a detection at or above the confident threshold;
    2. again: heard at least twice within the window;
    3. perch: Perch 2.0 agrees on the same window (second opinion);
    4. local: the species is regularly observed in Belgium at this time of year.

    A bird is confirmed as soon as **two** checks are done (three for a bird
    rescued by the silent check; a sure, common bird only once heard again). A
    species rarely observed locally therefore needs two acoustic checks
    (confident + heard again, or a check plus Perch agreeing). A skipped check
    never blocks: the bird can always be confirmed by being heard again, or is
    withdrawn when the window ends.
    """

    def __init__(
        self,
        min_confidence: float,
        window: timedelta,
        local_lookup: Callable[[str, datetime], str] | None = None,
    ):
        self.min_confidence = min_confidence
        self.window = window
        self.local_lookup = local_lookup
        self.pending: dict[str, Pending] = {}

    def observe(
        self,
        scientific: str,
        common: str,
        rarity: Rarity,
        observation: Observation,
        **mode: object,
    ) -> tuple[str, Pending]:
        """Adds a detection; ``mode`` (required, needs_repeat, perch) sets up a
        new entry only."""
        entry = self.pending.get(scientific)
        if entry is None or observation.when - entry.first_seen > self.window:
            entry = Pending(scientific, common, rarity, observation.when, **mode)
            if self.local_lookup is not None:
                entry.local = self.local_lookup(scientific, observation.when)
            self.pending[scientific] = entry
        entry.observations.append(observation)
        return self._settle(entry)

    def record_perch(self, entry: Pending, verdict: str) -> str:
        """Store Perch's verdict; returns "confirmed" or "provisional"."""
        keep = entry.perch == "agree" or (
            entry.perch == "disagree" and verdict.startswith("skipped")
        )
        if not keep:
            entry.perch = verdict
        state, _ = self._settle(entry)
        return state

    def needs_perch(self, entry: Pending) -> bool:
        return (
            entry.scientific in self.pending
            and entry.perch != "agree"
            and not entry.needs_repeat
        )

    def is_confirmed(self, entry: Pending) -> bool:
        if entry.needs_repeat:
            return len(entry.observations) >= 2
        return self.done_count(entry) >= entry.required

    def _settle(self, entry: Pending) -> tuple[str, Pending]:
        if self.is_confirmed(entry):
            self.pending.pop(entry.scientific, None)
            return "confirmed", entry
        return "provisional", entry

    @property
    def window_minutes(self) -> int:
        return int(self.window.total_seconds() // 60)

    def _confident(self, entry: Pending) -> list[Observation]:
        return [o for o in entry.observations if o.confidence >= self.min_confidence]

    def states(self, entry: Pending) -> dict[str, str]:
        perch = entry.perch
        local = entry.local
        return {
            "confident": "done" if self._confident(entry) else "pending",
            "again": "done" if len(entry.observations) >= 2 else "pending",
            "perch": "done"
            if perch == "agree"
            else "failed"
            if perch == "disagree"
            else "skipped",
            "local": "done"
            if local == "observed"
            else "failed"
            if local == "rare"
            else "skipped",
        }

    def done_count(self, entry: Pending) -> int:
        return sum(state == "done" for state in self.states(entry).values())

    def steps(self, entry: Pending, confirmed: bool = False) -> list[dict]:
        states = self.states(entry)
        names = {
            "confident": t("step_confident", threshold=self.min_confidence),
            "again": t("step_again", minutes=self.window_minutes),
            "perch": t("step_perch"),
            "local": t("step_local"),
        }
        notes = {
            "perch": _reason_note("perch", entry.perch),
            "local": _reason_note("local", entry.local),
        }
        return [
            {
                "key": key,
                "name": names[key],
                "state": states[key],
                "done": states[key] == "done",
                "note": notes.get(key, ""),
            }
            for key in STEP_KEYS
        ]

    def progress(self, entry: Pending, confirmed: bool = False) -> int:
        if confirmed:
            return 100
        if entry.needs_repeat:
            return 50
        done = min(self.done_count(entry), entry.required)
        return round(100 * done / entry.required)

    def minutes_left(self, entry: Pending, now: datetime) -> int:
        left = entry.first_seen + self.window - now
        return max(0, int(left.total_seconds() // 60))

    def expire(self, now: datetime) -> list[Pending]:
        expired = [e for e in self.pending.values() if now - e.first_seen > self.window]
        for entry in expired:
            del self.pending[entry.scientific]
        return expired


def _reason_note(check: str, value: str) -> str:
    """Household text explaining a check's outcome (empty when it is done)."""
    if value in ("agree", "observed"):
        return ""
    if value == "disagree":
        return t("note_perch_disagree")
    if value == "rare":
        return t("note_local_rare")
    reason = value.partition(":")[2] or "unavailable"
    key = f"note_{check}_{reason}"
    return t(key) if has_text(key) else t(f"note_{check}_unavailable")
