"""Home Assistant entities and the bird-detected event over MQTT (MOUL-23, MOUL-24).

Uses Home Assistant's MQTT discovery: the App announces its entities and Home
Assistant creates them under one device, "Mouflon Population". Only text is sent:
species, confidence, source, time, statuses. Never audio.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol

from mouflon_population import __version__, i18n

log = logging.getLogger(__name__)

DISCOVERY_PREFIX = "homeassistant"
BASE = "mouflon"
NODE = "mouflon_population"
AVAILABILITY_TOPIC = f"{BASE}/status"
EVENT_TOPIC = f"{BASE}/event"
LAST_BIRD_TOPIC = f"{BASE}/last_bird"
STATS_TOPIC = f"{BASE}/stats"
DEMO_TOPIC = f"{BASE}/demo_mode"
RARE_TOPIC = f"{BASE}/rare_bird"
SPECIES_TODAY_TOPIC = f"{BASE}/species_today"
EXPORT_COMMAND_TOPIC = f"{BASE}/command/export_analytics"
EXPORT_TOPIC = f"{BASE}/analytics_export"
DELAY_TOPIC = f"{BASE}/detection_delay"
SILENT_TOPIC = f"{BASE}/silent_check"
IMAGE_TOPIC = f"{BASE}/image"
TODAY_SLOTS = 6
LAST_BIRD_IMAGE = "last_bird_drawing"
SCREEN_IMAGES = ("screen", "screen_last_bird", "screen_today")
NO_BIRD = {
    "common_name": "",
    "scientific_name": "",
    "confidence": 0,
    "source": "",
    "detected_at": "",
    "demo": False,
}
DEVICE = {
    "identifiers": [NODE],
    "name": "Mouflon Population",
    "manufacturer": "Mouflon Population",
    "model": "BirdNET 2.4 bird detector",
    "sw_version": __version__,
}


class Transport(Protocol):
    def publish(
        self, topic: str, payload: str | bytes, retain: bool = False
    ) -> None: ...


@dataclass(frozen=True)
class Message:
    topic: str
    payload: str | bytes
    retain: bool


def image_entity_id(object_id: str) -> str:
    return f"image.{NODE}_{object_id}"


def slot_object_id(index: int) -> str:
    return f"today_{index + 1}_drawing"


def _common(unique: str, name: str) -> dict:
    return {
        "name": name,
        "unique_id": f"{NODE}_{unique}",
        "availability_topic": AVAILABILITY_TOPIC,
        "device": DEVICE,
    }


def _on_off(config: dict) -> dict:
    return {**config, "payload_on": "ON", "payload_off": "OFF"}


def _image(object_id: str, name: str, content_type: str) -> tuple[str, str, dict]:
    return (
        "image",
        object_id,
        {
            **_common(object_id, name),
            "image_topic": f"{IMAGE_TOPIC}/{object_id}",
            "content_type": content_type,
        },
    )


def _rarity_template(level: str) -> str:
    return (
        "{{ 'ON' if ((value_json.rarity or {}).get('tags') or [])"
        f" | selectattr('level', 'eq', '{level}') | list else 'OFF' }}}}"
    )


def discovery_messages(sources: list[tuple[str, str]]) -> list[Message]:
    """Discovery configs. ``sources`` is a list of ``(slug, display name)``."""
    name = i18n.entity_name
    configs: list[tuple[str, str, dict]] = [
        (
            "event",
            "bird_detected",
            {
                **_common("bird_detected", name("bird_detected")),
                "state_topic": EVENT_TOPIC,
                "event_types": ["bird_detected"],
                "icon": "mdi:bird",
            },
        ),
        (
            "sensor",
            "last_bird",
            {
                **_common("last_bird", name("last_bird")),
                "state_topic": LAST_BIRD_TOPIC,
                "value_template": "{{ value_json.common_name }}",
                "json_attributes_topic": LAST_BIRD_TOPIC,
                "icon": "mdi:bird",
            },
        ),
        (
            "event",
            "rare_bird",
            {
                **_common("rare_bird", name("rare_bird")),
                "state_topic": RARE_TOPIC,
                "event_types": ["rare_bird"],
                "icon": "mdi:star-shooting",
            },
        ),
        (
            "sensor",
            "last_bird_status",
            {
                **_common("last_bird_status", name("last_bird_status")),
                "state_topic": LAST_BIRD_TOPIC,
                "value_template": "{{ value_json.status | default('confirmed') }}",
                "icon": "mdi:progress-check",
            },
        ),
        (
            "sensor",
            "confirmation_progress",
            {
                **_common("confirmation_progress", name("confirmation_progress")),
                "state_topic": LAST_BIRD_TOPIC,
                "value_template": (
                    "{{ value_json.confirmation_progress | default(100) }}"
                ),
                "unit_of_measurement": "%",
                "icon": "mdi:progress-clock",
            },
        ),
        _image(LAST_BIRD_IMAGE, name(LAST_BIRD_IMAGE), "image/jpeg"),
        (
            "sensor",
            "species_today",
            {
                **_common("species_today", name("species_today")),
                "state_topic": STATS_TOPIC,
                "json_attributes_topic": SPECIES_TODAY_TOPIC,
                "value_template": "{{ value_json.species_today }}",
                "state_class": "measurement",
                "icon": "mdi:feather",
            },
        ),
        (
            "sensor",
            "detections_today",
            {
                **_common("detections_today", name("detections_today")),
                "state_topic": STATS_TOPIC,
                "value_template": "{{ value_json.detections_today }}",
                "state_class": "measurement",
                "icon": "mdi:counter",
            },
        ),
        (
            "sensor",
            "detection_delay",
            {
                **_common("detection_delay", name("detection_delay")),
                "state_topic": DELAY_TOPIC,
                "value_template": "{{ value_json.last_s }}",
                "json_attributes_topic": DELAY_TOPIC,
                "unit_of_measurement": "s",
                "device_class": "duration",
                "state_class": "measurement",
                "icon": "mdi:timer-sand",
            },
        ),
        # Silent check (0.20-0.50, owner's decision 2026-11-23): birds rescued today,
        # with the rejected and skipped counts as attributes. Never any audio.
        (
            "sensor",
            "silent_check",
            {
                **_common("silent_check", name("silent_check")),
                "state_topic": SILENT_TOPIC,
                "value_template": "{{ value_json.rescued }}",
                "json_attributes_topic": SILENT_TOPIC,
                "state_class": "total",
                "icon": "mdi:ear-hearing",
            },
        ),
        (
            "button",
            "export_analytics",
            {
                **_common("export_analytics", name("export_analytics")),
                "command_topic": EXPORT_COMMAND_TOPIC,
                "payload_press": "PRESS",
                "icon": "mdi:file-delimited",
            },
        ),
        (
            "sensor",
            "last_analytics_export",
            {
                **_common("last_analytics_export", name("last_analytics_export")),
                "state_topic": EXPORT_TOPIC,
                "value_template": "{{ value_json.file }}",
                "json_attributes_topic": EXPORT_TOPIC,
                "icon": "mdi:file-check",
            },
        ),
    ]
    configs += [_image(i, name(i), "image/png") for i in SCREEN_IMAGES]
    configs += [
        _image(slot_object_id(i), name("today_drawing", n=i + 1), "image/jpeg")
        for i in range(TODAY_SLOTS)
    ]
    # One on/off per rarity level, so a dashboard can hide empty rarity pills.
    configs += [
        (
            "binary_sensor",
            f"rarity_{level}",
            _on_off(
                {
                    **_common(f"rarity_{level}", name(f"rarity_{level}")),
                    "state_topic": LAST_BIRD_TOPIC,
                    "value_template": _rarity_template(level),
                }
            )
            | {"icon": "mdi:star-outline"},
        )
        for level in ("garden", "regional", "global")
    ]
    configs.append(
        (
            "binary_sensor",
            "demo_mode",
            _on_off(
                {**_common("demo_mode", name("demo_mode")), "state_topic": DEMO_TOPIC}
            )
            | {"icon": "mdi:test-tube"},
        )
    )
    for slug, source in sources:
        configs.append(
            (
                "sensor",
                f"{slug}_status",
                {
                    **_common(f"{slug}_status", name("source_status", name=source)),
                    "state_topic": f"{BASE}/source/{slug}/status",
                    "icon": "mdi:microphone-message",
                },
            )
        )
        configs.append(
            (
                "binary_sensor",
                f"{slug}_listening",
                _on_off(
                    {
                        **_common(
                            f"{slug}_listening", name("source_listening", name=source)
                        ),
                        "state_topic": f"{BASE}/source/{slug}/listening",
                    }
                )
                | {"icon": "mdi:ear-hearing"},
            )
        )
    return [
        Message(
            f"{DISCOVERY_PREFIX}/{component}/{NODE}/{object_id}/config",
            json.dumps(
                {**config, "default_entity_id": f"{component}.{NODE}_{object_id}"}
            ),
            True,
        )
        for component, object_id, config in configs
    ]


class Publisher:
    def __init__(self, transport: Transport):
        self._transport = transport

    def _send(self, message: Message) -> None:
        self._transport.publish(message.topic, message.payload, retain=message.retain)

    def announce(self, sources: list[tuple[str, str]]) -> None:
        for message in discovery_messages(sources):
            self._send(message)
        self._send(Message(AVAILABILITY_TOPIC, "online", True))

    def subscribe(self, topic: str, callback) -> None:
        subscribe = getattr(self._transport, "subscribe", None)
        if subscribe is not None:
            subscribe(topic, callback)

    def silent_check(self, counts: dict) -> None:
        self._send(Message(SILENT_TOPIC, json.dumps(counts), True))

    def delay(self, summary: dict) -> None:
        self._send(Message(DELAY_TOPIC, json.dumps(summary), True))

    def analytics_export(self, file: str, rows: int, at: str) -> None:
        payload = {"file": file, "rows": rows, "exported_at": at}
        self._send(Message(EXPORT_TOPIC, json.dumps(payload), True))

    def remove_sources(self, slugs: list[str]) -> None:
        """Delete source entities from Home Assistant (empty discovery config)."""
        for slug in slugs:
            for component, suffix in (
                ("sensor", "status"),
                ("binary_sensor", "listening"),
            ):
                topic = f"{DISCOVERY_PREFIX}/{component}/{NODE}/{slug}_{suffix}/config"
                self._send(Message(topic, "", True))

    def demo_mode(self, on: bool) -> None:
        self._send(Message(DEMO_TOPIC, "ON" if on else "OFF", True))

    def reset_last_bird(self, detection: dict | None = None) -> None:
        payload = (
            {**detection, "demo": bool(detection.get("demo", False))}
            if detection
            else {**NO_BIRD, "common_name": i18n.t("no_bird")}
        )
        self._send(Message(LAST_BIRD_TOPIC, json.dumps(payload), True))

    def rare_bird(self, detection: dict, demo: bool = False) -> None:
        payload = {"event_type": "rare_bird", **detection, "demo": demo}
        self._send(Message(RARE_TOPIC, json.dumps(payload), False))

    def species_today(self, species: list[dict]) -> None:
        self._send(Message(SPECIES_TODAY_TOPIC, json.dumps({"species": species}), True))

    def image(self, object_id: str, data: bytes) -> None:
        self._send(Message(f"{IMAGE_TOPIC}/{object_id}", data, True))

    def bird(self, detection: dict, demo: bool = False) -> None:
        detection = {**detection, "demo": demo}
        self._send(
            Message(
                EVENT_TOPIC,
                json.dumps({"event_type": "bird_detected", **detection}),
                False,
            )
        )
        self._send(Message(LAST_BIRD_TOPIC, json.dumps(detection), True))

    def stats(self, species_today: int, detections_today: int) -> None:
        payload = {"species_today": species_today, "detections_today": detections_today}
        self._send(Message(STATS_TOPIC, json.dumps(payload), True))

    def source_status(self, slug: str, status: str) -> None:
        text = i18n.status_text(status)
        self._send(Message(f"{BASE}/source/{slug}/status", text, True))
        listening = "ON" if status == "listening" else "OFF"
        self._send(Message(f"{BASE}/source/{slug}/listening", listening, True))


class PahoTransport:
    """MQTT connection with automatic reconnection and a last will ("offline")."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str = "",
        password: str = "",
        ssl: bool = False,
    ):
        import paho.mqtt.client as mqtt

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=NODE,
        )
        if username:
            self._client.username_pw_set(username, password)
        if ssl:
            self._client.tls_set()
        self._client.will_set(AVAILABILITY_TOPIC, "offline", retain=True)
        self._client.reconnect_delay_set(min_delay=2, max_delay=120)
        self._on_connect_callbacks: list = []
        self._subscriptions: dict = {}
        self._client.on_connect = self._on_connect
        self._client.connect_async(host, port, keepalive=60)
        self._client.loop_start()

    def on_connect(self, callback) -> None:
        self._on_connect_callbacks.append(callback)

    def subscribe(self, topic: str, callback) -> None:
        """Call ``callback()`` on messages to ``topic``; resubscribed on reconnect."""
        self._subscriptions[topic] = callback
        self._client.message_callback_add(topic, lambda *_: callback())
        self._client.subscribe(topic, qos=1)

    def _on_connect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            log.error("MQTT connection refused: %s", reason_code)
            return
        log.info("Connected to MQTT")
        for topic in self._subscriptions:
            self._client.subscribe(topic, qos=1)
        for callback in self._on_connect_callbacks:
            callback()

    def publish(self, topic: str, payload: str | bytes, retain: bool = False) -> None:
        self._client.publish(topic, payload, qos=1, retain=retain)

    def close(self) -> None:
        self._client.publish(AVAILABILITY_TOPIC, "offline", qos=1, retain=True)
        self._client.loop_stop()
        self._client.disconnect()
