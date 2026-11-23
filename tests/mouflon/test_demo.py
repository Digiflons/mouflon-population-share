import json
import random
import threading
from datetime import UTC, datetime, timedelta

from mouflon_population import config
from mouflon_population.birdlog import BirdLog, LoggedDetection
from mouflon_population.demo import (
    BELGIAN_GARDEN_BIRDS,
    DEMO_RARE,
    DemoRunner,
    activity,
)
from mouflon_population.detector import FilteringDetector
from mouflon_population.mqtt_publisher import Publisher
from mouflon_population.service import Service

DAWN = datetime(2026, 5, 10, 6, 0, tzinfo=UTC)


class Recorder:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, retain=False):
        self.messages.append((topic, payload, retain))

    def payloads(self, topic):
        return [json.loads(p) for t, p, _ in self.messages if t == topic and p]


class Home:
    def __init__(self, state, elevation):
        self.sun = {"state": state, "attributes": {"elevation": elevation}}

    def state_with_attributes(self, entity_id):
        assert entity_id == "sun.sun"
        return self.sun


def demo_settings(tmp_path):
    return config.from_dict(
        {
            "demo_mode": True,
            "test_mode": False,
            "sources": [
                {
                    "name": "Camera 1",
                    "type": "rtsp",
                    "url": "rtsp://hub/1",
                    "enabled": False,
                },
                {
                    "name": "Camera 2",
                    "type": "rtsp",
                    "url": "rtsp://hub/2",
                    "enabled": False,
                },
            ],
        },
        tmp_path / "data",
    )


def runner(tmp_path, home, transport, seed=1):
    return DemoRunner(
        demo_settings(tmp_path),
        Publisher(transport),
        home,
        rng=random.Random(seed),
        clock=lambda: DAWN,
        tick_s=600,
    )


def test_demo_is_never_night_and_has_busy_and_quiet_waves():
    start = datetime(2026, 5, 10, 0, 0, tzinfo=UTC)
    levels = [activity(start + timedelta(minutes=m)) for m in range(24 * 60)]
    assert min(levels) >= 0.2
    assert max(levels) > 0.9
    assert max(levels) >= 4 * min(levels)
    midnight = [activity(start + timedelta(seconds=s)) for s in range(0, 3600, 60)]
    assert sum(midnight) / len(midnight) > 0.2


def test_demo_detections_are_marked_as_fake_everywhere(tmp_path):
    transport = Recorder()
    demo = runner(tmp_path, Home("above_horizon", 3), transport)
    demo.announce()
    produced = [d for _ in range(5) for d in demo.tick()]
    assert produced

    belgian = {b[0] for b in BELGIAN_GARDEN_BIRDS} | {r[0] for r in DEMO_RARE}
    events = transport.payloads("mouflon/event")
    assert events
    for event in events:
        assert event["demo"] is True
        assert event["source"] in {"Démo Camera 1", "Démo Camera 2"}
        assert event["scientific_name"] in belgian
        assert 0.5 <= event["confidence"] < 1
    assert all(p["demo"] is True for p in transport.payloads("mouflon/last_bird"))
    assert ("mouflon/demo_mode", "ON", True) in transport.messages
    assert any(
        t == "homeassistant/binary_sensor/mouflon_population/demo_mode/config"
        for t, _, _ in transport.messages
    )
    assert ("mouflon/source/demo_camera_1/status", "démo", True) in transport.messages


def test_demo_birds_keep_coming_at_night(tmp_path):
    transport = Recorder()
    demo = runner(tmp_path, Home("below_horizon", -20), transport)
    demo.clock = lambda: DAWN.replace(hour=2)
    assert [d for _ in range(20) for d in demo.tick()]


def test_demo_data_never_reaches_the_real_bird_log(tmp_path, monkeypatch):
    monkeypatch.setattr("mouflon_population.demo.PEAK_PER_MINUTE", 60_000)
    real = BirdLog(tmp_path / "real" / "birdlog.sqlite")
    real.add(LoggedDetection(DAWN, "Camera 1", "Parus major", "Great Tit", 0.8))
    demo = runner(tmp_path, Home("above_horizon", 3), Recorder())
    stop = threading.Event()
    thread = threading.Thread(target=demo.run, args=(stop,))
    demo.tick_s = 0.01
    thread.start()
    while demo.stats.detections < 5:
        threading.Event().wait(0.01)
    stop.set()
    thread.join(timeout=5)

    assert [e.common_name for e in real.recent()] == ["Great Tit"]
    data_dir = tmp_path / "data"
    assert not data_dir.exists() or not any(data_dir.rglob("*"))


def test_switching_demo_off_resets_what_home_assistant_shows(tmp_path):
    settings = config.from_dict(
        {
            "test_mode": False,
            "sources": [
                {
                    "name": "Camera 1",
                    "type": "rtsp",
                    "url": "rtsp://hub/1",
                    "enabled": False,
                }
            ],
        },
        tmp_path / "data",
    )
    birdlog = BirdLog(settings.data_dir / "birdlog.sqlite")
    transport = Recorder()
    service = Service(
        settings,
        FilteringDetector(lambda _w: [], 0.5),
        Publisher(transport),
        birdlog,
        home=None,
        example_path=tmp_path,
        clock=lambda: DAWN,
    )
    service.announce()

    assert ("mouflon/demo_mode", "OFF", True) in transport.messages
    assert (
        "homeassistant/sensor/mouflon_population/demo_camera_1_status/config",
        "",
        True,
    ) in transport.messages
    assert (
        transport.payloads("mouflon/last_bird")[-1]["common_name"]
        == "Pas encore d'oiseau"
    )
    assert transport.payloads("mouflon/stats")[-1] == {
        "species_today": 0,
        "detections_today": 0,
    }
