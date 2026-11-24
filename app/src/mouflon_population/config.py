"""App settings, read from the options Home Assistant stores for the App.

Home Assistant writes the settings form to ``/data/options.json``. Passwords typed
there by the owner are registered with the log masker and never logged.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

from mouflon_population import masking

SOURCE_TYPES = ("rtsp", "file")
LISTENING_MODES = ("daylight", "windows", "always")
SUN_ENTITY = "sun.sun"
_WINDOW = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")
_SLUG = re.compile(r"[^a-z0-9]+")


class ConfigError(ValueError):
    pass


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = _SLUG.sub("_", ascii_name.lower()).strip("_")
    return slug or "source"


@dataclass(frozen=True)
class SourceConfig:
    name: str
    type: str
    url: str
    username: str = ""
    password: str = ""
    battery_entity: str = ""
    enabled: bool = True

    @property
    def slug(self) -> str:
        return slugify(self.name)

    @property
    def battery_powered(self) -> bool:
        return bool(self.battery_entity)


@dataclass(frozen=True)
class Window:
    start: time
    end: time

    def contains(self, moment: time) -> bool:
        if self.start <= self.end:
            return self.start <= moment < self.end
        return moment >= self.start or moment < self.end


@dataclass(frozen=True)
class Settings:
    sources: tuple[SourceConfig, ...]
    test_mode: bool = True
    demo_mode: bool = False
    min_confidence: float = 0.5
    language: str = "fr"
    species_filter: bool = True
    listening_mode: str = "daylight"
    listening_windows: tuple[Window, ...] = ()
    battery_stop_below: float = 40.0
    battery_resume_above: float = 60.0
    battery_max_drop_per_day: float = 15.0
    wind_entity: str = ""
    rain_entity: str = ""
    max_wind_kmh: float = 25.0
    log_retention_days: int = 365
    rare_garden_days: int = 3
    regional_threshold: float = 0.10
    rare_min_confidence: float = 0.75
    rare_confirm_minutes: int = 15
    second_opinion: bool = True
    second_opinion_threshold: float = 0.75
    silent_check_min: float = 0.20
    perch_agreement: float = 0.70
    common_confirm_twice: bool = True
    screen_enabled: bool = True
    screen_size: tuple[int, int] = (480, 800)
    screen_refresh_minutes: int = 10
    screen_view: str = "collage"
    data_dir: Path = field(default=Path("/data/mouflon"))


def parse_window(text: str) -> Window:
    match = _WINDOW.match(text)
    if not match:
        raise ConfigError(f"Listening window must look like 05:30-08:30, got {text!r}")
    h1, m1, h2, m2 = (int(g) for g in match.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        raise ConfigError(f"Listening window has an invalid time: {text!r}")
    return Window(time(h1, m1), time(h2, m2))


def parse_size(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"\s*(\d{3,4})\s*x\s*(\d{3,4})\s*", text.lower())
    if not match:
        raise ConfigError(f"Screen size must look like 480x800, got {text!r}")
    return int(match.group(1)), int(match.group(2))


def _source(raw: dict) -> SourceConfig:
    source = SourceConfig(
        name=str(raw.get("name", "")).strip(),
        type=str(raw.get("type", "rtsp")).strip(),
        url=str(raw.get("url", "")).strip(),
        username=str(raw.get("username") or ""),
        password=str(raw.get("password") or ""),
        battery_entity=str(raw.get("battery_entity") or "").strip(),
        enabled=bool(raw.get("enabled", True)),
    )
    if not source.name:
        raise ConfigError("Every source needs a name")
    if source.type not in SOURCE_TYPES:
        raise ConfigError(f"Source {source.name!r}: type must be one of {SOURCE_TYPES}")
    if not source.url:
        raise ConfigError(f"Source {source.name!r}: url is empty")
    if source.type == "rtsp" and "@" in source.url.split("//", 1)[-1].split("/", 1)[0]:
        raise ConfigError(
            f"Source {source.name!r}: put the login in the username and password "
            "fields, not inside the url"
        )
    masking.register_secret(source.password)
    return source


def from_dict(raw: dict, data_dir: Path | None = None) -> Settings:
    sources = tuple(_source(s) for s in raw.get("sources", []))
    slugs = [s.slug for s in sources]
    if len(set(slugs)) != len(slugs):
        raise ConfigError("Two sources have the same name")
    settings = Settings(
        sources=sources,
        test_mode=bool(raw.get("test_mode", True)),
        demo_mode=bool(raw.get("demo_mode", False)),
        min_confidence=float(raw.get("min_confidence", 0.5)),
        language=str(raw.get("language", "fr")),
        species_filter=bool(raw.get("species_filter", True)),
        listening_mode=str(raw.get("listening_mode", "daylight")),
        listening_windows=tuple(
            parse_window(w) for w in raw.get("listening_windows", []) or []
        ),
        battery_stop_below=float(raw.get("battery_stop_below", 40)),
        battery_resume_above=float(raw.get("battery_resume_above", 60)),
        battery_max_drop_per_day=float(raw.get("battery_max_drop_per_day", 15)),
        wind_entity=str(raw.get("wind_entity") or "").strip(),
        rain_entity=str(raw.get("rain_entity") or "").strip(),
        max_wind_kmh=float(raw.get("max_wind_kmh", 25)),
        log_retention_days=int(raw.get("log_retention_days", 365)),
        rare_garden_days=int(raw.get("rare_garden_days", 3)),
        regional_threshold=float(raw.get("regional_threshold", 0.10)),
        rare_min_confidence=float(raw.get("rare_min_confidence", 0.75)),
        rare_confirm_minutes=int(raw.get("rare_confirm_minutes", 15)),
        second_opinion=bool(raw.get("second_opinion", True)),
        second_opinion_threshold=float(raw.get("second_opinion_threshold", 0.75)),
        silent_check_min=float(raw.get("silent_check_min", 0.20)),
        perch_agreement=float(raw.get("perch_agreement", 0.70)),
        common_confirm_twice=bool(raw.get("common_confirm_twice", True)),
        screen_enabled=bool(raw.get("screen_enabled", True)),
        screen_size=parse_size(str(raw.get("screen_size", "480x800"))),
        screen_refresh_minutes=int(raw.get("screen_refresh_minutes", 10)),
        screen_view=str(raw.get("screen_view", "collage")),
        data_dir=data_dir or Path("/data/mouflon"),
    )
    if settings.demo_mode and settings.test_mode:
        raise ConfigError(
            "Demo mode and test mode cannot both be on: turn one of them off"
        )
    if settings.demo_mode and any(s.enabled for s in settings.sources):
        raise ConfigError(
            "Demo mode cannot run with enabled audio sources: disable the sources "
            "or turn demo mode off"
        )
    if settings.listening_mode not in LISTENING_MODES:
        raise ConfigError(f"listening_mode must be one of {LISTENING_MODES}")
    if not 0 < settings.min_confidence < 1:
        raise ConfigError("min_confidence must be between 0 and 1")
    if settings.battery_resume_above <= settings.battery_stop_below:
        raise ConfigError("battery_resume_above must be higher than battery_stop_below")
    if settings.rare_min_confidence < settings.min_confidence:
        raise ConfigError("rare_min_confidence must be at least min_confidence")
    if settings.second_opinion_threshold < settings.min_confidence:
        raise ConfigError("second_opinion_threshold must be at least min_confidence")
    if settings.silent_check_min > settings.min_confidence:
        raise ConfigError("silent_check_min must not be above min_confidence")
    if not 0 < settings.perch_agreement < 1:
        raise ConfigError("perch_agreement must be between 0 and 1")
    if settings.log_retention_days < 1:
        raise ConfigError("log_retention_days must be at least 1")
    return settings


def load(path: Path, data_dir: Path | None = None) -> Settings:
    with path.open(encoding="utf-8") as f:
        return from_dict(json.load(f), data_dir)
