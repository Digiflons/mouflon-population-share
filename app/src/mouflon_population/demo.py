"""Demo mode (MOUL-41): invented bird detections to fill Home Assistant.

No audio and no model are used: nothing is listened to. Detections of common
Belgian garden birds are drawn at random on a compressed 45-minute "day" with busy
and quieter waves; it is never night in demo mode (MOUL-50), whatever the real sun.
Everything is marked as fake:

- the sources are named "Démo <camera>";
- every detection and event carries ``demo: true``;
- the "Demo mode" binary sensor is on;
- the start-up log says demo mode is on.

Demo detections are counted in memory only and never reach the real bird log.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING

from mouflon_population import i18n
from mouflon_population.config import slugify
from mouflon_population.gallery import Gallery
from mouflon_population.rarity import assess

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from mouflon_population.config import Settings
    from mouflon_population.ha import HomeAssistant
    from mouflon_population.library import Library
    from mouflon_population.mqtt_publisher import Publisher

log = logging.getLogger(__name__)

DEMO_PREFIX = "Démo"
DEFAULT_CAMERAS = ("Camera 1", "Camera 2")
TICK_S = 15.0
DEMO_DAY_MINUTES = 45
MIN_ACTIVITY = 0.2
# Detections per minute per source at the busiest moment of the demo day.
PEAK_PER_MINUTE = 1.2

# (scientific name, common name, relative frequency)
BELGIAN_GARDEN_BIRDS: tuple[tuple[str, str, float], ...] = (
    ("Turdus merula", "Eurasian Blackbird", 10),
    ("Erithacus rubecula", "European Robin", 8),
    ("Parus major", "Great Tit", 8),
    ("Cyanistes caeruleus", "Eurasian Blue Tit", 7),
    ("Columba palumbus", "Common Wood-Pigeon", 6),
    ("Fringilla coelebs", "Common Chaffinch", 6),
    ("Passer domesticus", "House Sparrow", 6),
    ("Pica pica", "Eurasian Magpie", 4),
    ("Troglodytes troglodytes", "Eurasian Wren", 5),
    ("Prunella modularis", "Dunnock", 4),
    ("Streptopelia decaocto", "Eurasian Collared-Dove", 3),
    ("Sturnus vulgaris", "European Starling", 3),
    ("Phylloscopus collybita", "Common Chiffchaff", 3),
    ("Sylvia atricapilla", "Eurasian Blackcap", 2),
    ("Garrulus glandarius", "Eurasian Jay", 1),
    ("Dendrocopos major", "Great Spotted Woodpecker", 1),
)


# Occasional demo rarities: (scientific, common, garden, regional, iucn).
DEMO_RARE: tuple[tuple[str, str, str, str, str | None], ...] = (
    ("Upupa epops", "Eurasian Hoopoe", "new", "unusual", None),
    ("Streptopelia turtur", "European Turtle-Dove", "rare", "usual", "VU"),
    ("Dryobates minor", "Lesser Spotted Woodpecker", "new", "usual", None),
)
RARE_SHARE = 0.03
# BirdNET's French labels, used when the App's language is French.
FRENCH_NAMES = {
    "Turdus merula": "Merle noir",
    "Erithacus rubecula": "Rougegorge familier",
    "Parus major": "Mésange charbonnière",
    "Cyanistes caeruleus": "Mésange bleue",
    "Columba palumbus": "Pigeon ramier",
    "Fringilla coelebs": "Pinson des arbres",
    "Passer domesticus": "Moineau domestique",
    "Pica pica": "Pie bavarde",
    "Troglodytes troglodytes": "Troglodyte mignon",
    "Prunella modularis": "Accenteur mouchet",
    "Streptopelia decaocto": "Tourterelle turque",
    "Sturnus vulgaris": "Étourneau sansonnet",
    "Phylloscopus collybita": "Pouillot véloce",
    "Sylvia atricapilla": "Fauvette à tête noire",
    "Garrulus glandarius": "Geai des chênes",
    "Dendrocopos major": "Pic épeiche",
    "Upupa epops": "Huppe fasciée",
    "Streptopelia turtur": "Tourterelle des bois",
    "Dryobates minor": "Pic épeichette",
}


def demo_name(scientific: str, english: str) -> str:
    if i18n.current() == "fr":
        return FRENCH_NAMES.get(scientific, english)
    return english


def demo_source_names(settings: Settings) -> list[str]:
    cameras = [s.name for s in settings.sources] or list(DEFAULT_CAMERAS)
    return [f"{DEMO_PREFIX} {name}" for name in cameras]


def activity(now: datetime) -> float:
    """Demo activity on a compressed day (MOUL-50): never zero, never night.

    One demo "day" lasts DEMO_DAY_MINUTES, with a busy dawn wave and a busy dusk
    wave and a quieter middle; the real sun is ignored.
    """
    phase = (now.timestamp() / 60 % DEMO_DAY_MINUTES) / DEMO_DAY_MINUTES
    dawn = math.exp(-(((phase - 0.15) / 0.08) ** 2))
    dusk = math.exp(-(((phase - 0.8) / 0.08) ** 2))
    return MIN_ACTIVITY + (1 - MIN_ACTIVITY) * max(dawn, dusk)


def _poisson(rng: random.Random, mean: float) -> int:
    limit, count, product = math.exp(-mean), 0, rng.random()
    while product > limit:
        count += 1
        product *= rng.random()
    return count


@dataclass
class DemoStats:
    day: date | None = None
    species: dict[str, dict] = field(default_factory=dict)
    rarity: dict[str, dict] = field(default_factory=dict)
    detections: int = 0

    def add(self, when: datetime, scientific: str, common: str, rarity: dict) -> None:
        if when.date() != self.day:
            self.day, self.species, self.rarity, self.detections = (
                when.date(),
                {},
                {},
                0,
            )
        item = self.species.setdefault(
            scientific,
            {"scientific_name": scientific, "common_name": common, "count": 0},
        )
        item["count"] += 1
        item["last_heard"] = when.isoformat(timespec="seconds")
        self.rarity.setdefault(scientific, rarity)
        self.detections += 1

    def today(self) -> list[dict]:
        return sorted(
            (dict(v) for v in self.species.values()),
            key=lambda v: v["last_heard"],
            reverse=True,
        )


class DemoRunner:
    def __init__(
        self,
        settings: Settings,
        publisher: Publisher,
        home: HomeAssistant,
        rng: random.Random | None = None,
        clock: Callable[[], datetime] | None = None,
        tick_s: float = TICK_S,
        library: Library | None = None,
    ):
        self.publisher = publisher
        self.home = home
        self.rng = rng or random.Random()
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.tick_s = tick_s
        self.sources = demo_source_names(settings)
        self.stats = DemoStats()
        self.pending: dict[str, dict] = {}
        self.library = library
        self.gallery = Gallery(
            publisher,
            library,
            settings.screen_size if settings.screen_enabled else None,
            settings.screen_refresh_minutes * 60,
            settings.screen_view,
        )
        self._names = [b[:2] for b in BELGIAN_GARDEN_BIRDS]
        self._weights = [b[2] for b in BELGIAN_GARDEN_BIRDS]

    def announce(self) -> None:
        self.publisher.announce([(slugify(n), n) for n in self.sources])
        self.publisher.demo_mode(True)
        self.publisher.stats(0, 0)
        self.gallery.show_last(None)
        self.gallery.show_species([], {})
        for name in self.sources:
            self.publisher.source_status(slugify(name), "demo")

    def tick(self) -> list[dict]:
        now = self.clock()
        mean = activity(now) * PEAK_PER_MINUTE * self.tick_s / 60
        produced = []
        for source in self.sources:
            for _ in range(_poisson(self.rng, mean)):
                if self.rng.random() < RARE_SHARE:
                    scientific, common, garden, regional, iucn = self.rng.choice(
                        DEMO_RARE
                    )
                    common = demo_name(scientific, common)
                    if scientific not in self.stats.species:
                        self._start_provisional(
                            scientific, common, garden, regional, iucn, source, now
                        )
                        continue
                    rarity = assess(garden, regional, iucn)
                    rarity.status = "confirmed"
                else:
                    scientific, common = self.rng.choices(self._names, self._weights)[0]
                    common = demo_name(scientific, common)
                    entry = self.library.get(scientific) if self.library else None
                    rarity = assess("regular", "usual", entry.iucn if entry else None)
                    rarity.status = "confirmed" if rarity.is_rare else "none"
                detection = {
                    "detected_at": now.isoformat(timespec="seconds"),
                    "source": source,
                    "scientific_name": scientific,
                    "common_name": common,
                    "confidence": round(min(0.99, self.rng.betavariate(6, 2)), 3),
                }
                if detection["confidence"] < 0.5:
                    continue
                detection["rarity"] = rarity.as_dict()
                detection.update(
                    status="confirmed",
                    confirmation_progress=100,
                    confirmation_steps=[],
                    minutes_left=0,
                )
                first_today = scientific not in self.stats.species
                self.stats.add(now, scientific, common, rarity.as_dict())
                enriched = self.gallery.enrich(detection)
                self.publisher.bird(enriched, demo=True)
                self.gallery.show_last(scientific)
                if rarity.is_rare and first_today:
                    self.publisher.rare_bird(enriched, demo=True)
                produced.append(detection)
        changed = self._advance_provisional(now)
        if produced or changed:
            self.publisher.stats(len(self.stats.species), self.stats.detections)
            self.gallery.show_species(self._species_list(), self.stats.rarity)
        self.gallery.render_screen_if_due(now)
        return produced

    # --- provisional flow, shown occasionally in demo mode (MOUL-53) ----------------

    def _steps(self, done: int) -> list[dict]:
        return [
            {"name": "Confident detection (≥ 0.75)", "done": done >= 1},
            {"name": "Heard again within 15 min", "done": done >= 2},
        ]

    def _start_provisional(
        self, scientific, common, garden, regional, iucn, source, now
    ):
        if scientific in self.pending:
            return
        self.pending[scientific] = {
            "scientific_name": scientific,
            "common_name": common,
            "source": source,
            "rarity": (garden, regional, iucn),
            "ticks": 0,
            "outcome": "confirm" if self.rng.random() < 0.75 else "withdraw",
            "started": now,
        }
        self._publish_pending(self.pending[scientific], now, "provisional", 1)

    def _publish_pending(self, item, now, status, done) -> None:
        detection = {
            "detected_at": now.isoformat(timespec="seconds"),
            "source": item["source"],
            "scientific_name": item["scientific_name"],
            "common_name": item["common_name"],
            "confidence": 0.8,
            "rarity": {
                "garden": None,
                "regional": None,
                "iucn": None,
                "status": status,
                "tags": [],
                "labels": [],
            },
            "status": status,
            "confirmation_progress": 100 * done // 2,
            "confirmation_steps": self._steps(done),
            "minutes_left": max(0, 15 - 5 * item["ticks"])
            if status == "provisional"
            else 0,
        }
        enriched = self.gallery.enrich(detection)
        if status == "withdrawn":
            self.publisher.reset_last_bird({**enriched, "demo": True})
        else:
            self.publisher.bird(enriched, demo=True)
            self.gallery.show_last(item["scientific_name"])

    def _advance_provisional(self, now) -> bool:
        changed = False
        for scientific, item in list(self.pending.items()):
            item["ticks"] += 1
            changed = True
            if item["outcome"] == "confirm" and item["ticks"] >= 2:
                del self.pending[scientific]
                garden, regional, iucn = item["rarity"]
                rarity = assess(garden, regional, iucn)
                rarity.status = "confirmed"
                detection = {
                    "detected_at": now.isoformat(timespec="seconds"),
                    "source": item["source"],
                    "scientific_name": scientific,
                    "common_name": item["common_name"],
                    "confidence": 0.86,
                    "rarity": rarity.as_dict(),
                    "status": "confirmed",
                    "confirmation_progress": 100,
                    "confirmation_steps": self._steps(2),
                    "minutes_left": 0,
                }
                self.stats.add(now, scientific, item["common_name"], rarity.as_dict())
                enriched = self.gallery.enrich(detection)
                self.publisher.bird(enriched, demo=True)
                self.gallery.show_last(scientific)
                self.publisher.rare_bird(enriched, demo=True)
            elif item["outcome"] == "withdraw" and item["ticks"] >= 3:
                del self.pending[scientific]
                self._publish_pending(item, now, "withdrawn", 1)
            else:
                self._publish_pending(item, now, "provisional", 1)
        return changed

    def _species_list(self) -> list[dict]:
        confirmed = [
            {**item, "status": "confirmed", "confirmation_progress": 100}
            for item in self.stats.today()
        ]
        provisional = [
            {
                "scientific_name": item["scientific_name"],
                "common_name": item["common_name"],
                "count": 1,
                "last_heard": item["started"].isoformat(timespec="seconds"),
                "status": "provisional",
                "confirmation_progress": 50,
                "confirmation_steps": self._steps(1),
                "minutes_left": max(0, 15 - 5 * item["ticks"]),
            }
            for item in self.pending.values()
        ]
        return sorted(
            confirmed + provisional, key=lambda i: i["last_heard"], reverse=True
        )

    def run(self, stop: threading.Event) -> None:
        log.warning(
            "DEMO MODE ON: invented bird detections for display only. "
            "No audio, no model, nothing stored in the bird log."
        )
        self.announce()
        while not stop.wait(self.tick_s):
            self.tick()
