import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from mouflon_population import config
from mouflon_population.birdlog import BirdLog
from mouflon_population.detector import FilteringDetector
from mouflon_population.guards import Reading
from mouflon_population.ha import HomeLocation
from mouflon_population.mqtt_publisher import Publisher
from mouflon_population.service import Service, birdnet_week

EXAMPLE = Path(__file__).resolve().parents[2] / "app/example/soundscape-60s.flac"
NOW = datetime(2026, 5, 10, 7, 0, tzinfo=UTC)


class Recorder:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, retain=False):
        self.messages.append((topic, payload, retain))

    def topics(self):
        return [t for t, _, _ in self.messages]


class FakeHome:
    def __init__(self, battery=None):
        self.battery = battery
        self.read = []

    def state(self, entity_id):
        self.read.append(entity_id)
        return Reading(self.battery, NOW)

    location = None

    def home_location(self):
        return self.location

    def raw_state(self, entity_id):
        self.read.append(entity_id)
        return self.sun

    sun = "above_horizon"


def fake_predict(window):
    assert window.dtype.name == "float32"
    return [
        ("Turdus merula_Eurasian Blackbird", 0.9),
        ("Human vocal_Human vocal", 0.95),
    ]


def make_service(tmp_path, raw, home, transport, species_lookup=None):
    settings = config.from_dict(raw, tmp_path / "data")
    birdlog = BirdLog(settings.data_dir / "birdlog.sqlite")
    service = Service(
        settings,
        FilteringDetector(fake_predict, settings.min_confidence),
        Publisher(transport),
        birdlog,
        home,
        EXAMPLE,
        species_lookup=species_lookup,
        clock=lambda: NOW,
        guard_interval_s=0.05,
        realtime_replay=False,
    )
    return service, birdlog


def run_until(service, condition, timeout=20):
    stop = threading.Event()
    thread = threading.Thread(target=service.run, args=(stop,))
    thread.start()
    deadline = datetime.now().timestamp() + timeout
    while not condition() and datetime.now().timestamp() < deadline:
        threading.Event().wait(0.05)
    stop.set()
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_week_calendar():
    assert birdnet_week(datetime(2026, 1, 1)) == 1
    assert birdnet_week(datetime(2026, 12, 31)) == 48


def test_test_mode_runs_the_whole_chain_without_keeping_audio(tmp_path):
    transport = Recorder()
    service, birdlog = make_service(
        tmp_path, {"test_mode": True}, FakeHome(), transport
    )
    run_until(service, lambda: len(birdlog.recent()) >= 3)

    entries = birdlog.recent()
    assert entries
    assert {e.common_name for e in entries} == {"Eurasian Blackbird"}
    assert {e.source for e in entries} == {"Test recording"}

    events = [json.loads(p) for t, p, _ in transport.messages if t == "mouflon/event"]
    assert events
    assert all(e["event_type"] == "bird_detected" for e in events)
    assert all("Human" not in p for _, p, _ in transport.messages if isinstance(p, str))
    assert (
        "homeassistant/event/mouflon_population/bird_detected/config"
        in transport.topics()
    )

    files = {p.name for p in (tmp_path / "data").rglob("*") if p.is_file()}
    assert files <= {"birdlog.sqlite", "birdlog.sqlite-journal"}


def test_low_battery_never_opens_the_camera(tmp_path, monkeypatch):
    opened = []

    class Camera:
        name = "Camera 1"

        def windows(self, stop):
            opened.append(True)
            yield from ()

    monkeypatch.setattr(
        "mouflon_population.service.build_source", lambda *a, **k: Camera()
    )
    raw = {
        "test_mode": False,
        "sources": [
            {
                "name": "Camera 1",
                "type": "rtsp",
                "url": "rtsp://192.0.2.10:554/stream1",
                "battery_entity": "sensor.camera_1_battery",
            }
        ],
    }
    transport = Recorder()
    home = FakeHome(battery=20)
    service, _ = make_service(tmp_path, raw, home, transport)
    run_until(
        service,
        lambda: (
            ("mouflon/source/camera_1/status", "paused: battery low (20 %)", True)
            in transport.messages
        ),
    )
    assert "sensor.camera_1_battery" in home.read
    assert ("mouflon/source/camera_1/listening", "OFF", True) in transport.messages
    assert opened == []


def test_after_sunset_the_camera_is_not_opened(tmp_path, monkeypatch):
    opened = []

    class Camera:
        name = "Camera 1"

        def windows(self, stop):
            opened.append(True)
            yield from ()

    monkeypatch.setattr(
        "mouflon_population.service.build_source", lambda *a, **k: Camera()
    )
    raw = {
        "test_mode": False,
        "sources": [
            {
                "name": "Camera 1",
                "type": "rtsp",
                "url": "rtsp://192.0.2.10:554/stream1",
                "battery_entity": "sensor.camera_1_battery",
            }
        ],
    }
    transport = Recorder()
    home = FakeHome(battery=90)
    home.sun = "below_horizon"
    service, _ = make_service(tmp_path, raw, home, transport)
    run_until(
        service,
        lambda: (
            ("mouflon/source/camera_1/status", "outside daylight", True)
            in transport.messages
        ),
    )
    assert "sun.sun" in home.read
    assert opened == []


BELGIUM = HomeLocation(50.85, 4.35, "Europe/Brussels")


def test_test_mode_turns_the_species_filter_off(tmp_path, caplog):
    home = FakeHome()
    home.location = BELGIUM
    lookups = []

    def belgian_species(lat, lon, week):
        lookups.append((lat, lon, week))
        return frozenset({"Parus major"})

    transport = Recorder()
    service, birdlog = make_service(
        tmp_path, {"test_mode": True}, home, transport, belgian_species
    )
    with caplog.at_level(logging.INFO, logger="mouflon_population"):
        run_until(service, lambda: len(birdlog.recent()) >= 1)
    assert service.detector.allowed_species is None
    assert lookups == []
    assert "species filter off" in caplog.text


def test_dropped_detections_are_counted_in_the_log(tmp_path, caplog):
    home = FakeHome()
    home.location = BELGIUM
    service, birdlog = make_service(
        tmp_path,
        {"test_mode": False, "sources": []},
        home,
        Recorder(),
        lambda lat, lon, week: frozenset({"Parus major"}),
    )
    service.refresh_species_filter()
    assert service.detector.allowed_species == frozenset({"Parus major"})
    source = config.SourceConfig(name="Camera 1", type="rtsp", url="rtsp://hub/1")
    with caplog.at_level(logging.INFO, logger="mouflon_population"):
        kept = service.handle_window(source, np.zeros(3, dtype="float32"))
    assert kept == 0
    assert (
        "Camera 1: 1 detection(s) dropped by the species filter: Eurasian Blackbird"
        in (caplog.text)
    )
    assert birdlog.recent() == []
