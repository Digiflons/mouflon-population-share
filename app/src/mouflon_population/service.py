"""Runs the chain: source -> guards -> BirdNET -> filters -> bird log + MQTT.

One thread per source. Each window of sound is analysed and then dropped; only the
filtered detections go further.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from mouflon_population import __version__, masking
from mouflon_population.analytics import AnalyticsRow
from mouflon_population.birdlog import BirdLog, LoggedDetection
from mouflon_population.config import SUN_ENTITY, Settings, SourceConfig, slugify
from mouflon_population.detector import MODEL_LABEL
from mouflon_population.gallery import Gallery
from mouflon_population.guards import (
    BatteryGuard,
    Verdict,
    daylight_verdict,
    weather_verdict,
    window_verdict,
)
from mouflon_population.latency import Delay, LatencyTracker
from mouflon_population.mqtt_publisher import EXPORT_COMMAND_TOPIC
from mouflon_population.rarity import (
    ConfirmationTracker,
    Observation,
    Pending,
    Rarity,
    assess,
    garden_level,
    regional_level,
)
from mouflon_population.sources import (
    AudioSource,
    FileSource,
    StreamSource,
    reconnecting_windows,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mouflon_population.analytics import AnalyticsStore
    from mouflon_population.detector import FilteringDetector
    from mouflon_population.ha import HomeAssistant
    from mouflon_population.library import Library
    from mouflon_population.mqtt_publisher import Publisher

log = logging.getLogger(__name__)

LAST_BIRD_ENTITY = "sensor.mouflon_population_last_bird"

GUARD_INTERVAL_S = 60.0
TEST_SOURCE = SourceConfig(name="Test recording", type="file", url="")


def birdnet_week(day: datetime) -> int:
    """BirdNET's 48-week calendar: four 'weeks' per month."""
    return (day.month - 1) * 4 + min(4, math.ceil(day.day / 7))


def build_source(
    config: SourceConfig, example_path: Path, realtime: bool = True
) -> AudioSource:
    if config.type == "file":
        return FileSource(config.name, config.url or example_path, realtime)
    return StreamSource(config.name, config.url, config.username, config.password)


class Service:
    def __init__(
        self,
        settings: Settings,
        detector: FilteringDetector,
        publisher: Publisher,
        birdlog: BirdLog,
        home: HomeAssistant,
        example_path: Path,
        species_lookup: Callable[[float, float, int], frozenset[str]] | None = None,
        clock: Callable[[], datetime] | None = None,
        guard_interval_s: float = GUARD_INTERVAL_S,
        realtime_replay: bool = True,
        library: Library | None = None,
        analytics: AnalyticsStore | None = None,
        export_dir: Path | None = None,
    ):
        self.settings = settings
        self.detector = detector
        self.publisher = publisher
        self.birdlog = birdlog
        self.home = home
        self.example_path = example_path
        self.species_lookup = species_lookup
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.guard_interval_s = guard_interval_s
        self.realtime_replay = realtime_replay
        self._battery_guards = {
            s.slug: BatteryGuard(
                settings.battery_stop_below,
                settings.battery_resume_above,
                settings.battery_max_drop_per_day,
            )
            for s in settings.sources
        }
        self._stats_lock = threading.Lock()
        self.gallery = Gallery(
            publisher,
            library,
            settings.screen_size if settings.screen_enabled else None,
            settings.screen_refresh_minutes * 60,
            settings.screen_view,
        )
        self.library = library
        self.geo_probabilities: dict[str, float] | None = None
        self.tracker = ConfirmationTracker(
            settings.rare_min_confidence,
            timedelta(minutes=settings.rare_confirm_minutes),
        )
        self.latency = LatencyTracker()
        self._last_published: dict | None = None
        self.rarity_today: dict[str, dict] = {}
        # Never for test mode: the analytics table holds real garden detections only.
        self.analytics = None if settings.test_mode else analytics
        self.export_dir = export_dir
        self._rare_announced: set[str] = set()

    @property
    def active_sources(self) -> list[SourceConfig]:
        if self.settings.test_mode:
            return [TEST_SOURCE]
        return [s for s in self.settings.sources if s.enabled]

    def announce(self) -> None:
        self.publisher.subscribe(EXPORT_COMMAND_TOPIC, self.export_analytics)
        from mouflon_population.demo import demo_source_names

        self.publisher.announce([(s.slug, s.name) for s in self.active_sources])
        # Real mode: clear anything a previous demo run left in Home Assistant.
        self.publisher.demo_mode(False)
        self.publisher.remove_sources(
            [slugify(n) for n in demo_source_names(self.settings)]
        )
        latest = self.birdlog.recent(limit=1)
        self.publisher.reset_last_bird(
            self.gallery.enrich(latest[0].as_dict()) if latest else None
        )
        self.gallery.show_last(latest[0].scientific_name if latest else None)
        self.publish_stats()

    def refresh_species_filter(self) -> None:
        if self.settings.test_mode:
            log.info(
                "Test mode: species filter off (the bundled test recording is from "
                "North America, so a local filter would drop all its birds)"
            )
            self.detector.allowed_species = None
            return
        if not self.settings.species_filter or self.species_lookup is None:
            self.detector.allowed_species = None
            return
        location = self.home.home_location()
        if location is None:
            log.warning("No home location: species filter off")
            self.detector.allowed_species = None
            return
        try:
            found = self.species_lookup(
                location.latitude, location.longitude, birdnet_week(self.clock())
            )
            if isinstance(found, dict):
                self.geo_probabilities = found
            self.detector.allowed_species = frozenset(found)
        except Exception as error:
            log.warning("Species filter unavailable: %s", error)
            self.detector.allowed_species = None

    def timing_verdict(self, now: datetime) -> Verdict:
        mode = self.settings.listening_mode
        if mode == "daylight":
            return daylight_verdict(self.home.raw_state(SUN_ENTITY))
        if mode == "windows":
            return window_verdict(self.settings.listening_windows, now)
        return Verdict(True, "ok")

    def verdict(self, source: SourceConfig) -> Verdict:
        if self.settings.test_mode:
            return Verdict(True, "ok")
        now = self.clock()
        checks = [self.timing_verdict(now)]
        if source.battery_powered:
            reading = self.home.state(source.battery_entity)
            checks.append(self._battery_guards[source.slug].check(reading, now))
        if self.settings.wind_entity or self.settings.rain_entity:
            wind = (
                self.home.state(self.settings.wind_entity).value
                if self.settings.wind_entity
                else None
            )
            rain = (
                self.home.state(self.settings.rain_entity).value
                if self.settings.rain_entity
                else None
            )
            checks.append(weather_verdict(wind, rain, self.settings.max_wind_kmh))
        for check in checks:
            if not check.allowed:
                return check
        return Verdict(True, "ok")

    def handle_window(self, source: SourceConfig, window) -> int:
        started = time.monotonic()
        detections = self.detector.detect(window)
        del window
        inference_s = time.monotonic() - started
        dropped = getattr(self.detector, "last_dropped", [])
        if dropped:
            log.info(
                "%s: %d detection(s) dropped by the species filter: %s",
                source.name,
                len(dropped),
                ", ".join(dropped),
            )
        now = self.clock()
        logged = 0
        for detection in detections:
            observation = Observation(now, source.name, detection.confidence)
            rarity = self.rarity_of(detection.scientific, now)
            already = self.rarity_today.get(detection.scientific)
            publish_started = time.monotonic()
            if already is not None or not rarity.is_rare:
                display = Rarity.from_dict(already) if already else rarity
                logged += self._confirm(detection, [observation], display, now)
            else:
                state, entry = self.tracker.observe(
                    detection.scientific, detection.common, rarity, observation
                )
                if state == "confirmed":
                    rarity.status = "confirmed"
                    logged += self._confirm(
                        detection, entry.observations, rarity, now, entry=entry
                    )
                else:
                    self._show_provisional(entry, now)
            self._measure(inference_s, time.monotonic() - publish_started, now)
        if logged:
            self.publish_stats()
        return logged

    def _progress_fields(
        self, entry: Pending | None, now: datetime, status: str
    ) -> dict:
        if entry is None:
            return {
                "status": status,
                "confirmation_progress": 100 if status == "confirmed" else 0,
                "confirmation_steps": [],
                "minutes_left": 0,
            }
        confirmed = status == "confirmed"
        return {
            "status": status,
            "confirmation_progress": self.tracker.progress(entry, confirmed),
            "confirmation_steps": self.tracker.steps(entry, confirmed),
            "minutes_left": 0
            if status != "provisional"
            else self.tracker.minutes_left(entry, now),
        }

    def _confirm(self, detection, observations, rarity, now, entry=None) -> int:
        for seen in observations:
            self.birdlog.add(
                LoggedDetection(
                    detected_at=seen.when,
                    source=seen.source,
                    scientific_name=detection.scientific,
                    common_name=detection.common,
                    confidence=seen.confidence,
                )
            )
            self._record_analytics(
                detection.scientific, detection.common, seen, rarity, "confirmed"
            )
        self.rarity_today.setdefault(detection.scientific, rarity.as_dict())
        last = observations[-1]
        payload = {
            "detected_at": last.when.isoformat(timespec="seconds"),
            "source": last.source,
            "scientific_name": detection.scientific,
            "common_name": detection.common,
            "confidence": detection.confidence,
            "rarity": rarity.as_dict(),
            **self._progress_fields(entry, now, "confirmed"),
        }
        enriched = self.gallery.enrich(payload)
        self.publisher.bird(enriched, demo=False)
        self.gallery.show_last(detection.scientific)
        self._last_published = enriched
        if rarity.is_rare and detection.scientific not in self._rare_announced:
            self._rare_announced.add(detection.scientific)
            self.publisher.rare_bird(enriched, demo=False)
        log.info(
            "%s: %s (%.0f %%)%s",
            last.source,
            detection.common,
            detection.confidence * 100,
            f" — {', '.join(rarity.as_dict()['labels'])}" if rarity.is_rare else "",
        )
        return len(observations)

    def _show_provisional(self, entry: Pending, now: datetime) -> None:
        """Show the most plausible bird right away; rarity waits for confirmation."""
        last = entry.observations[-1]
        hidden = {
            "garden": None,
            "regional": None,
            "iucn": None,
            "status": "provisional",
            "tags": [],
            "labels": [],
        }
        payload = {
            "detected_at": last.when.isoformat(timespec="seconds"),
            "source": last.source,
            "scientific_name": entry.scientific,
            "common_name": entry.common,
            "confidence": max(o.confidence for o in entry.observations),
            "rarity": hidden,
            **self._progress_fields(entry, now, "provisional"),
        }
        enriched = self.gallery.enrich(payload)
        self.publisher.bird(enriched, demo=False)
        self.gallery.show_last(entry.scientific)
        self._last_published = enriched
        log.info(
            "%s: %s (%.0f %%) provisional, confirming (%d%%, %d min left)",
            last.source,
            entry.common,
            last.confidence * 100,
            payload["confirmation_progress"],
            payload["minutes_left"],
        )
        self.publish_stats()

    def expire_provisional(self, now: datetime) -> list[str]:
        withdrawn = []
        for entry in self.tracker.expire(now):
            withdrawn.append(entry.scientific)
            for seen in entry.observations:
                self._record_analytics(
                    entry.scientific, entry.common, seen, entry.rarity, "withdrawn"
                )
            log.info("%s not confirmed within the window: withdrawn", entry.common)
            last = self._last_published
            if last and last.get("scientific_name") == entry.scientific:
                self.publisher.reset_last_bird(
                    {**last, **self._progress_fields(entry, now, "withdrawn")}
                )
        if withdrawn:
            self.publish_stats()
        return withdrawn

    def _record_analytics(self, scientific, common, seen, rarity, status) -> None:
        if self.analytics is None:
            return
        self.analytics.add(
            AnalyticsRow(
                detected_at=seen.when,
                scientific_name=scientific,
                common_name=common,
                confidence=seen.confidence,
                source=seen.source,
                garden_rarity=rarity.garden,
                regional_rarity=rarity.regional,
                iucn=rarity.iucn,
                status=status,
                app_version=__version__,
                model_version=MODEL_LABEL,
            )
        )

    def _measure(self, inference_s: float, publish_s: float, now: datetime) -> None:
        delay = Delay(inference_s, publish_s, self._home_assistant_delay(now))
        summary = self.latency.add(delay)
        self.publisher.delay(summary)
        log.info(
            "Detection delay %.2f s (inference %.2f s, publish %.3f s, "
            "Home Assistant %s)",
            delay.total_s,
            delay.inference_s,
            delay.publish_s,
            "n/a"
            if delay.home_assistant_s is None
            else f"{delay.home_assistant_s:.2f} s",
        )

    def _home_assistant_delay(self, published_at: datetime) -> float | None:
        """Seconds until Home Assistant reports the new last-bird state, if readable."""
        if not getattr(self.home, "available", False):
            return None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            data = self.home.state_with_attributes(LAST_BIRD_ENTITY)
            reported = (data or {}).get("last_reported") or (data or {}).get(
                "last_updated"
            )
            if reported:
                try:
                    seen = datetime.fromisoformat(reported)
                except ValueError:
                    return None
                if seen >= published_at:
                    return max(0.0, (seen - published_at).total_seconds())
            time.sleep(0.2)
        return None

    def export_analytics(self) -> Path | None:
        if self.analytics is None or self.export_dir is None:
            log.warning("Analytics export unavailable (test mode or no export folder)")
            return None
        now = self.clock()
        target, rows = self.analytics.export_csv(self.export_dir, now)
        self.publisher.analytics_export(
            target.name, rows, now.isoformat(timespec="seconds")
        )
        log.info("Analytics exported: %s (%d rows)", target.name, rows)
        return target

    def rarity_of(self, scientific: str, now: datetime):
        if self.settings.test_mode:
            # The test recording is foreign: no garden or regional rarity in test mode.
            return assess("regular", "unknown", None)
        first_ever, days = self.birdlog.history(scientific, now - timedelta(days=365))
        garden = garden_level(first_ever, days, self.settings.rare_garden_days)
        probability = (
            self.geo_probabilities.get(scientific)
            if self.geo_probabilities is not None
            else None
        )
        regional = regional_level(probability, self.settings.regional_threshold)
        entry = self.library.get(scientific) if self.library else None
        return assess(garden, regional, entry.iucn if entry else None)

    def publish_stats(self) -> None:
        with self._stats_lock:
            now = self.clock()
            stats = self.birdlog.day_stats(now)
            self.publisher.stats(stats.species, stats.detections)
            confirmed = [
                {**item, "status": "confirmed", "confirmation_progress": 100}
                for item in self.birdlog.day_species(now)
            ]
            provisional = [
                {
                    "scientific_name": e.scientific,
                    "common_name": e.common,
                    "count": len(e.observations),
                    "last_heard": e.observations[-1].when.isoformat(timespec="seconds"),
                    **self._progress_fields(e, now, "provisional"),
                }
                for e in self.tracker.pending.values()
                if e.scientific not in {c["scientific_name"] for c in confirmed}
            ]
            species = sorted(
                confirmed + provisional, key=lambda i: i["last_heard"], reverse=True
            )
            self.gallery.show_species(species, self.rarity_today)

    def run_source(self, config: SourceConfig, stop: threading.Event) -> None:
        source = build_source(config, self.example_path, self.realtime_replay)
        last_status = None

        def status(value: str) -> None:
            nonlocal last_status
            if value != last_status:
                last_status = value
                self.publisher.source_status(config.slug, value)
                log.info("%s: %s", config.name, value)

        while not stop.is_set():
            verdict = self.verdict(config)
            if not verdict.allowed:
                status(verdict.reason)
                stop.wait(self.guard_interval_s)
                continue
            session_stop = threading.Event()
            watcher = threading.Thread(
                target=self._watch, args=(config, stop, session_stop), daemon=True
            )
            watcher.start()
            for window in reconnecting_windows(source, session_stop, status):
                self.handle_window(config, window)
            session_stop.set()
            watcher.join()
        status("stopped")

    def _watch(
        self, config: SourceConfig, stop: threading.Event, session_stop: threading.Event
    ) -> None:
        """Ends a listening session when the guards say stop (lets cameras sleep)."""
        waited = 0.0
        step = min(1.0, self.guard_interval_s)
        while not session_stop.wait(step):
            if stop.is_set():
                session_stop.set()
                return
            waited += step
            if waited >= self.guard_interval_s:
                waited = 0.0
                if not self.verdict(config).allowed:
                    session_stop.set()

    def daily_maintenance(self) -> None:
        self.rarity_today = {}
        self._rare_announced = set()
        removed = self.birdlog.purge(self.clock())
        if removed:
            log.info("Bird log: removed %d entries older than the retention", removed)
        self.refresh_species_filter()
        self.publish_stats()

    def run(self, stop: threading.Event) -> None:
        self.refresh_species_filter()
        self.announce()
        threads = [
            threading.Thread(
                target=self.run_source, args=(s, stop), name=s.slug, daemon=True
            )
            for s in self.active_sources
        ]
        for thread in threads:
            thread.start()
        log.info(
            "Listening to %s",
            ", ".join(masking.mask(s.name) for s in self.active_sources) or "nothing",
        )
        day = self.clock().date()
        self.gallery.render_screen_if_due(self.clock())
        while not stop.wait(self.guard_interval_s):
            self.expire_provisional(self.clock())
            self.gallery.render_screen_if_due(self.clock())
            today = self.clock().date()
            if today != day:
                day = today
                self.daily_maintenance()
        for thread in threads:
            thread.join(timeout=30)
