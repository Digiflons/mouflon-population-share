import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from mouflon_population import config
from mouflon_population.analytics import AnalyticsStore
from mouflon_population.birdlog import BirdLog
from mouflon_population.demo import DemoRunner
from mouflon_population.detector import FilteringDetector
from mouflon_population.latency import Delay, LatencyTracker
from mouflon_population.mqtt_publisher import Publisher, discovery_messages
from mouflon_population.service import Service

START = datetime(2026, 5, 10, 7, 0, tzinfo=UTC)
EXAMPLE = Path(__file__).resolve().parents[2] / "app/example/soundscape-60s.flac"


class Recorder:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, retain=False):
        self.messages.append((topic, payload, retain))

    def subscribe(self, topic, callback):
        pass

    def json(self, topic):
        return [json.loads(p) for t, p, _ in self.messages if t == topic and p]


class Home:
    available = False

    def raw_state(self, entity_id):
        return "above_horizon"

    def home_location(self):
        return None


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now


def build(tmp_path, confidence):
    clock = Clock()
    settings = config.from_dict({"test_mode": False, "sources": []}, tmp_path / "data")
    transport = Recorder()
    analytics = AnalyticsStore(tmp_path / "analytics.sqlite")
    service = Service(
        settings,
        FilteringDetector(
            lambda _w: [("Upupa epops_Eurasian Hoopoe", confidence())], 0.5
        ),
        Publisher(transport),
        BirdLog(settings.data_dir / "birdlog.sqlite"),
        Home(),
        EXAMPLE,
        clock=clock,
        analytics=analytics,
    )
    source = config.SourceConfig(name="Camera 1", type="rtsp", url="rtsp://h/1")
    return service, transport, analytics, clock, source


WINDOW = np.zeros(3, dtype="float32")


def test_a_first_time_bird_shows_at_once_as_provisional_then_confirms(tmp_path):
    service, transport, analytics, clock, source = build(tmp_path, lambda: 0.9)
    service.handle_window(source, WINDOW)

    last = transport.json("mouflon/last_bird")[-1]
    assert last["common_name"] == "Eurasian Hoopoe"
    assert last["status"] == "provisional"
    assert last["confirmation_progress"] == 50
    steps = last["confirmation_steps"]
    assert [s["key"] for s in steps] == ["confident", "again", "perch", "local"]
    assert [s["state"] for s in steps] == ["done", "pending", "skipped", "skipped"]
    assert steps[2]["name"] == "Deuxième avis (Perch) concordant"
    assert steps[2]["note"] == "Perch indisponible"
    assert steps[3]["name"] == "Observé localement à cette période"
    assert last["minutes_left"] == 15
    assert last["rarity"]["tags"] == []  # rarity pills wait for confirmation
    assert transport.json("mouflon/rare_bird") == []
    species = transport.json("mouflon/species_today")[-1]["species"]
    assert species[0]["status"] == "provisional"
    assert analytics.count() == 0

    clock.now += timedelta(minutes=6)
    service.handle_window(source, WINDOW)
    last = transport.json("mouflon/last_bird")[-1]
    assert last["status"] == "confirmed"
    assert last["confirmation_progress"] == 100
    assert "Nouveau pour le jardin" in last["rarity"]["labels"]
    assert len(transport.json("mouflon/rare_bird")) == 1
    assert analytics.count("confirmed") == 2


def test_an_unconfirmed_bird_is_withdrawn_and_never_counted(tmp_path):
    service, transport, analytics, clock, source = build(tmp_path, lambda: 0.9)
    service.handle_window(source, WINDOW)
    clock.now += timedelta(minutes=16)
    assert service.expire_provisional(clock.now) == ["Upupa epops"]

    last = transport.json("mouflon/last_bird")[-1]
    assert last["status"] == "withdrawn"
    species = transport.json("mouflon/species_today")[-1]["species"]
    assert all(s["scientific_name"] != "Upupa epops" for s in species)
    assert transport.json("mouflon/rare_bird") == []
    assert analytics.count("confirmed") == 0
    assert analytics.count("withdrawn") == 1
    assert service.birdlog.recent() == []


def test_a_weak_detection_starts_at_zero_progress(tmp_path):
    service, transport, _, _, source = build(tmp_path, lambda: 0.6)
    service.handle_window(source, WINDOW)
    last = transport.json("mouflon/last_bird")[-1]
    assert last["status"] == "provisional"
    assert last["confirmation_progress"] == 0


def test_delay_sensor_has_last_median_p95_and_breakdown(tmp_path):
    service, transport, _, _, source = build(tmp_path, lambda: 0.9)
    service.handle_window(source, WINDOW)
    delay = transport.json("mouflon/detection_delay")[-1]
    assert delay["samples"] == 1
    assert delay["last_s"] is not None
    assert set(delay["breakdown"]) == {
        "stream_lag_s",
        "inference_s",
        "publish_s",
        "home_assistant_s",
    }
    topics = {m.topic for m in discovery_messages([])}
    assert "homeassistant/sensor/mouflon_population/detection_delay/config" in topics


def test_latency_statistics():
    tracker = LatencyTracker()
    for value in [1.0] * 18 + [5.0, 9.0]:
        summary = tracker.add(Delay(value, 0.0))
    assert summary["median_s"] == 1.0
    assert summary["p95_s"] == 5.0  # nearest-rank 95th percentile of 20 values
    assert summary["samples"] == 20


def test_demo_shows_the_confirmation_flow(tmp_path, monkeypatch):
    monkeypatch.setattr("mouflon_population.demo.RARE_SHARE", 1.0)
    monkeypatch.setattr("mouflon_population.demo.PEAK_PER_MINUTE", 600)
    settings = config.from_dict({"demo_mode": True, "test_mode": False}, tmp_path)
    transport = Recorder()
    demo = DemoRunner(
        settings,
        Publisher(transport),
        Home(),
        rng=random.Random(5),
        clock=lambda: START,
        tick_s=60,
    )
    for _ in range(6):
        demo.tick()
    statuses = {p.get("status") for p in transport.json("mouflon/last_bird")}
    statuses |= {p.get("status") for p in transport.json("mouflon/event")}
    assert "provisional" in statuses
    assert "confirmed" in statuses
    assert all(p["demo"] for p in transport.json("mouflon/event"))
