"""User-facing text, French by default (owner's decision, 2026-11-22).

Everything a household user reads (entity names, statuses, rarity labels,
confirmation steps, the e-ink screen) comes from here. Logs and developer docs stay
in English. Bird names come from BirdNET's labels in the chosen language.

The language follows the App's ``language`` option: French for ``fr``, English for
every other choice (the other languages only change BirdNET's bird names).
"""

from __future__ import annotations

import re

TEXTS: dict[str, dict[str, str]] = {
    "fr": {
        "tag_new": "Nouveau pour le jardin",
        "tag_new_short": "Nouveau ici",
        "tag_rare": "Rare au jardin",
        "tag_rare_short": "Rare ici",
        "tag_unusual": "Inhabituel en Belgique",
        "tag_unusual_short": "Inhabituel",
        "iucn_NT": "Quasi menacé",
        "iucn_VU": "Vulnérable",
        "iucn_EN": "En danger",
        "iucn_CR": "En danger critique",
        "step_confident": "Détection sûre (≥ {threshold:.2f})",
        "step_again": "Entendu à nouveau en moins de {minutes} min",
        "no_bird": "Pas encore d'oiseau",
        "drawing_to_come": "Gravure à venir",
        "status_connecting": "connexion",
        "status_listening": "à l'écoute",
        "status_offline": "hors ligne",
        "status_demo": "démo",
        "status_battery_unknown": "en pause : batterie inconnue",
        "status_battery_old": "en pause : niveau de batterie trop ancien",
        "status_battery_low": "en pause : batterie faible ({value} %)",
        "status_battery_fast": "en pause : batterie qui baisse vite ({value} %/jour)",
        "status_night": "en dehors de la journée",
        "status_sun_unknown": "en pause : position du soleil inconnue",
        "status_window": "en dehors des heures d'écoute",
        "status_wind": "en pause : vent ({value} km/h)",
        "status_rain": "en pause : pluie",
    },
    "en": {
        "tag_new": "New for the garden",
        "tag_new_short": "New here",
        "tag_rare": "Rare in the garden",
        "tag_rare_short": "Rare here",
        "tag_unusual": "Unusual for Belgium now",
        "tag_unusual_short": "Unusual now",
        "iucn_NT": "Near threatened",
        "iucn_VU": "Vulnerable",
        "iucn_EN": "Endangered",
        "iucn_CR": "Critically endangered",
        "step_confident": "Confident detection (≥ {threshold:.2f})",
        "step_again": "Heard again within {minutes} min",
        "no_bird": "No bird yet",
        "drawing_to_come": "Drawing to come",
        "status_connecting": "connecting",
        "status_listening": "listening",
        "status_offline": "offline",
        "status_demo": "demo",
        "status_battery_unknown": "paused: battery unknown",
        "status_battery_old": "paused: battery reading too old",
        "status_battery_low": "paused: battery low ({value} %)",
        "status_battery_fast": "paused: battery dropping fast ({value} %/day)",
        "status_night": "outside daylight",
        "status_sun_unknown": "paused: sun position unknown",
        "status_window": "outside listening window",
        "status_wind": "paused: wind ({value} km/h)",
        "status_rain": "paused: rain",
    },
}

# Entity names in Home Assistant. Entity ids stay fixed (default_entity_id), so
# dashboards and automations work in every language.
ENTITY_NAMES: dict[str, dict[str, str]] = {
    "fr": {
        "bird_detected": "Oiseau détecté",
        "last_bird": "Dernier oiseau",
        "rare_bird": "Oiseau rare",
        "last_bird_status": "État du dernier oiseau",
        "confirmation_progress": "Progression de la confirmation",
        "last_bird_drawing": "Gravure du dernier oiseau",
        "species_today": "Espèces aujourd'hui",
        "detections_today": "Détections aujourd'hui",
        "detection_delay": "Délai de détection",
        "export_analytics": "Exporter les statistiques (CSV)",
        "last_analytics_export": "Dernier export des statistiques",
        "screen": "Écran",
        "screen_last_bird": "Écran : dernier oiseau",
        "screen_today": "Écran : oiseaux du jour",
        "today_drawing": "Gravure de l'oiseau du jour {n}",
        "demo_mode": "Mode démo",
        "rarity_garden": "Rareté au jardin",
        "rarity_regional": "Rareté régionale",
        "rarity_global": "Statut de conservation",
        "source_status": "État de {name}",
        "source_listening": "{name} à l'écoute",
    },
    "en": {
        "bird_detected": "Bird detected",
        "last_bird": "Last bird",
        "rare_bird": "Rare bird",
        "last_bird_status": "Last bird status",
        "confirmation_progress": "Confirmation progress",
        "last_bird_drawing": "Last bird drawing",
        "species_today": "Species today",
        "detections_today": "Detections today",
        "detection_delay": "Detection delay",
        "export_analytics": "Export bird analytics (CSV)",
        "last_analytics_export": "Last analytics export",
        "screen": "Screen",
        "screen_last_bird": "Screen: last bird",
        "screen_today": "Screen: today's birds",
        "today_drawing": "Today's bird {n} drawing",
        "demo_mode": "Demo mode",
        "rarity_garden": "Garden rarity",
        "rarity_regional": "Regional rarity",
        "rarity_global": "Conservation status",
        "source_status": "{name} status",
        "source_listening": "{name} listening",
    },
}

STATUS_WORDS = {
    "fr": {
        "provisional": "Confirmation en cours",
        "confirmed": "Confirmé",
        "withdrawn": "Non confirmé",
    },
    "en": {
        "provisional": "Confirmation in progress",
        "confirmed": "Confirmed",
        "withdrawn": "Not confirmed",
    },
}

_STATUS_PATTERNS = [
    (re.compile(r"^connecting$"), "status_connecting"),
    (re.compile(r"^listening$"), "status_listening"),
    (re.compile(r"^offline$"), "status_offline"),
    (re.compile(r"^demo$"), "status_demo"),
    (re.compile(r"^paused: battery unknown$"), "status_battery_unknown"),
    (re.compile(r"^paused: battery reading too old$"), "status_battery_old"),
    (re.compile(r"^paused: battery low \((?P<value>\d+) %\)$"), "status_battery_low"),
    (
        re.compile(r"^paused: battery dropping fast \((?P<value>\d+) %/day\)$"),
        "status_battery_fast",
    ),
    (re.compile(r"^outside daylight$"), "status_night"),
    (re.compile(r"^paused: sun position unknown$"), "status_sun_unknown"),
    (re.compile(r"^outside listening window$"), "status_window"),
    (re.compile(r"^paused: wind \((?P<value>\d+) km/h\)$"), "status_wind"),
    (re.compile(r"^paused: rain$"), "status_rain"),
]

_language = "fr"


def ui_language(language: str) -> str:
    return "fr" if language.lower().startswith("fr") else "en"


def configure(language: str) -> None:
    global _language  # noqa: PLW0603 - one App-wide setting, set once at start-up
    _language = ui_language(language)


def current() -> str:
    return _language


def t(key: str, **values: object) -> str:
    return TEXTS[_language][key].format(**values)


def entity_name(key: str, **values: object) -> str:
    return ENTITY_NAMES[_language][key].format(**values)


def status_text(status: str) -> str:
    """A source status (an English code from the guards) for a household user."""
    for pattern, key in _STATUS_PATTERNS:
        if match := pattern.match(status):
            return t(key, **match.groupdict())
    return status
