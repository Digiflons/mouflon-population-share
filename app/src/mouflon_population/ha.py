"""Read-only access to Home Assistant through the Supervisor.

Home Assistant gives the App a token in ``SUPERVISOR_TOKEN``, scoped to this App.
The App only *reads*: entity states (camera battery, wind, rain), the home location
and time zone, and the MQTT broker details the Mosquitto App shares with other Apps.
It never calls Home Assistant services.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from mouflon_population.guards import Reading

log = logging.getLogger(__name__)

SUPERVISOR_URL = "http://supervisor"
TIMEOUT_S = 10


@dataclass(frozen=True)
class MqttBroker:
    host: str
    port: int
    username: str
    password: str
    ssl: bool = False


@dataclass(frozen=True)
class HomeLocation:
    latitude: float
    longitude: float
    time_zone: str


class HomeAssistant:
    def __init__(self, token: str | None = None, base_url: str = SUPERVISOR_URL):
        self._token = (
            token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        )
        self._base = base_url.rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self._token)

    def _get(self, path: str) -> dict:
        request = urllib.request.Request(
            f"{self._base}{path}",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            return json.load(response)

    def state(self, entity_id: str) -> Reading:
        try:
            data = self._get(f"/core/api/states/{entity_id}")
        except Exception as error:
            log.warning("Cannot read %s: %s", entity_id, error)
            return Reading(None, None)
        return reading_from_state(data)

    def state_with_attributes(self, entity_id: str) -> dict | None:
        try:
            return self._get(f"/core/api/states/{entity_id}")
        except Exception as error:
            log.warning("Cannot read %s: %s", entity_id, error)
            return None

    def raw_state(self, entity_id: str) -> str | None:
        try:
            return str(self._get(f"/core/api/states/{entity_id}")["state"])
        except Exception as error:
            log.warning("Cannot read %s: %s", entity_id, error)
            return None

    def home_location(self) -> HomeLocation | None:
        override = _location_from_environment()
        if override is not None:
            return override
        try:
            data = self._get("/core/api/config")
            return HomeLocation(
                float(data["latitude"]), float(data["longitude"]), data["time_zone"]
            )
        except Exception as error:
            log.warning("Cannot read the home location: %s", error)
            return None

    def mqtt_broker(self) -> MqttBroker | None:
        try:
            data = self._get("/services/mqtt")["data"]
            return MqttBroker(
                host=data["host"],
                port=int(data["port"]),
                username=data.get("username", ""),
                password=data.get("password", ""),
                ssl=bool(data.get("ssl", False)),
            )
        except Exception as error:
            log.warning("No MQTT broker shared by the Supervisor: %s", error)
            return None


def _location_from_environment() -> HomeLocation | None:
    """Home location for runs outside Home Assistant (standalone container, CI)."""
    latitude = os.environ.get("MOUFLON_HOME_LATITUDE")
    longitude = os.environ.get("MOUFLON_HOME_LONGITUDE")
    if not latitude or not longitude:
        return None
    return HomeLocation(
        float(latitude), float(longitude), os.environ.get("TZ", "Europe/Brussels")
    )


def reading_from_state(data: dict) -> Reading:
    try:
        value = float(data["state"])
    except (KeyError, TypeError, ValueError):
        return Reading(None, None)
    updated = data.get("last_reported") or data.get("last_updated")
    try:
        updated_at = datetime.fromisoformat(updated) if updated else None
    except ValueError:
        updated_at = None
    return Reading(value, updated_at)
