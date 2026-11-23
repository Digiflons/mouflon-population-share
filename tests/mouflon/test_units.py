import json
import logging
import shutil
import threading
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pytest
from mouflon_population import WINDOW_SAMPLES, config, masking
from mouflon_population.birdlog import ALLOWED_COLUMNS, BirdLog, LoggedDetection
from mouflon_population.detector import (
    FilteringDetector,
    filter_detections,
    parse_label,
)
from mouflon_population.guards import (
    BatteryGuard,
    Reading,
    daylight_verdict,
    weather_verdict,
    window_verdict,
)
from mouflon_population.ha import reading_from_state
from mouflon_population.models import fingerprints, verify
from mouflon_population.mqtt_publisher import Publisher, discovery_messages
from mouflon_population.preview import render
from mouflon_population.sources import (
    SourceError,
    StreamSource,
    ffmpeg_command,
    reconnecting_windows,
    url_with_login,
)

NOW = datetime(2026, 5, 10, 7, 0, tzinfo=UTC)


class TestMasking:
    def test_masks_the_password_in_a_stream_url(self):
        assert masking.mask("rtsp://viewer:s3cret@10.0.0.2:554/x") == (
            "rtsp://viewer:***@10.0.0.2:554/x"
        )

    def test_masks_a_registered_secret_anywhere(self):
        masking.register_secret("hunter2-pass")
        assert "hunter2-pass" not in masking.mask("error: bad password hunter2-pass")

    def test_log_records_are_masked(self, caplog):
        logger = logging.getLogger("mask-test")
        handler = logging.StreamHandler()
        handler.addFilter(masking.SecretFilter())
        logger.addHandler(handler)
        with caplog.at_level(logging.INFO, logger="mask-test"):
            caplog.handler.addFilter(masking.SecretFilter())
            logger.info("opening %s", "rtsp://a:topsecret@hub/1")
        assert "topsecret" not in caplog.text


class TestConfig:
    def _raw(self, **extra):
        raw = {
            "sources": [
                {
                    "name": "Camera 2",
                    "type": "rtsp",
                    "url": "rtsp://192.0.2.10:554/stream2",
                    "username": "viewer",
                    "password": "pw-camera-2",
                    "battery_entity": "sensor.camera_2_battery",
                }
            ],
            "listening_windows": ["05:30-08:30", "22:00-01:00"],
        }
        raw.update(extra)
        return raw

    def test_reads_the_options(self, tmp_path):
        settings = config.from_dict(self._raw(), tmp_path)
        source = settings.sources[0]
        assert source.slug == "camera_2"
        assert source.battery_powered
        assert settings.test_mode is True
        assert settings.listening_mode == "daylight"
        assert settings.listening_windows[1].contains(time(0, 30))
        assert not settings.listening_windows[0].contains(time(9, 0))

    def test_registers_passwords_for_masking(self, tmp_path):
        config.from_dict(self._raw(), tmp_path)
        assert masking.mask("pw-camera-2") == "***"

    def test_demo_mode_excludes_test_mode_and_real_sources(self, tmp_path):
        with pytest.raises(config.ConfigError, match="test mode"):
            config.from_dict({"demo_mode": True, "test_mode": True}, tmp_path)
        raw = self._raw(demo_mode=True, test_mode=False)
        with pytest.raises(config.ConfigError, match="enabled audio sources"):
            config.from_dict(raw, tmp_path)
        raw["sources"][0]["enabled"] = False
        assert config.from_dict(raw, tmp_path).demo_mode

    def test_slugs_drop_accents(self):
        assert config.slugify("Démo Camera 2") == "demo_camera_2"

    def test_refuses_a_login_inside_the_url(self, tmp_path):
        raw = self._raw()
        raw["sources"][0]["url"] = "rtsp://admin:pw@192.168.1.20/x"
        with pytest.raises(config.ConfigError, match="username and password"):
            config.from_dict(raw, tmp_path)

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("min_confidence", 1.5),
            ("battery_resume_above", 30),
            ("listening_windows", ["25:00-26:00"]),
            ("log_retention_days", 0),
            ("listening_mode", "night"),
        ],
    )
    def test_refuses_invalid_values(self, tmp_path, key, value):
        with pytest.raises(config.ConfigError):
            config.from_dict(self._raw(**{key: value}), tmp_path)


class TestSources:
    def test_login_is_url_encoded(self):
        url = url_with_login("rtsp://10.0.0.2:554/p", "view er", "p@ss:w/rd")
        assert url == "rtsp://view%20er:p%40ss%3Aw%2Frd@10.0.0.2:554/p"

    def test_ffmpeg_keeps_sound_only_and_writes_to_a_pipe(self):
        command = ffmpeg_command("rtsp://hub/1")
        assert "-vn" in command
        assert command[-1] == "pipe:1"
        assert "-timeout" in command

    def test_reconnects_after_a_failure_and_reports_states(self):
        attempts = []

        class Flaky:
            name = "flaky"

            def windows(self, stop):
                attempts.append(1)
                if len(attempts) == 1:
                    raise RuntimeError("rtsp://u:secret@hub refused")
                yield np.zeros(WINDOW_SAMPLES, dtype="float32")
                stop.set()

        states = []
        stop = threading.Event()
        windows = list(
            reconnecting_windows(Flaky(), stop, states.append, first_delay_s=0.01)
        )
        assert len(windows) == 1
        assert states == ["connecting", "offline", "connecting", "listening"]


class TestDetector:
    RAW = (
        ("Turdus merula_Eurasian Blackbird", 0.91),
        ("Turdus merula_Eurasian Blackbird", 0.6),
        ("Human vocal_Human vocal", 0.99),
        ("Human whistle_Human whistle", 0.8),
        ("Engine_Engine", 0.9),
        ("Parus major_Great Tit", 0.3),
        ("Erithacus rubecula_European Robin", 0.7),
    )

    def test_parse_label(self):
        assert parse_label("Parus major_Great Tit") == ("Parus major", "Great Tit")

    def test_drops_human_sounds_non_species_and_weak_detections(self):
        kept = filter_detections(self.RAW, 0.5)
        assert [d.common for d in kept] == ["Eurasian Blackbird", "European Robin"]
        assert kept[0].confidence == 0.91

    def test_species_filter(self):
        kept = filter_detections(self.RAW, 0.5, {"Erithacus rubecula"})
        assert [d.scientific for d in kept] == ["Erithacus rubecula"]

    def test_filtering_detector_uses_the_current_species_list(self):
        detector = FilteringDetector(lambda _w: self.RAW, 0.5)
        detector.allowed_species = frozenset({"Turdus merula"})
        assert [d.common for d in detector.detect(np.zeros(3))] == [
            "Eurasian Blackbird"
        ]


class TestBirdLog:
    def test_keeps_only_species_confidence_source_and_time(self, tmp_path):
        log = BirdLog(tmp_path / "log.sqlite")
        assert log.columns() == ALLOWED_COLUMNS

    def test_stats_and_purge(self, tmp_path):
        log = BirdLog(tmp_path / "log.sqlite", retention_days=30)
        for when, name in [
            (NOW, "Turdus merula"),
            (NOW, "Turdus merula"),
            (NOW, "Parus major"),
            (NOW - timedelta(days=40), "Parus major"),
        ]:
            log.add(LoggedDetection(when, "Camera 1", name, name, 0.8))
        assert log.day_stats(NOW).species == 2
        assert log.day_stats(NOW).detections == 3
        assert log.purge(NOW) == 1
        assert len(log.recent()) == 3


class TestGuards:
    def guard(self):
        return BatteryGuard(stop_below=40, resume_above=60, max_drop_per_day=15)

    def test_unknown_or_stale_battery_fails_safe(self):
        guard = self.guard()
        assert not guard.check(Reading(None, None), NOW).allowed
        assert not guard.check(Reading(90, NOW - timedelta(hours=7)), NOW).allowed

    def test_stops_below_threshold_and_resumes_only_above_restart_level(self):
        guard = self.guard()
        assert guard.check(Reading(45, NOW), NOW).allowed
        later = NOW + timedelta(days=2)
        assert not guard.check(Reading(39, later), later).allowed
        assert not guard.check(Reading(50, later), later).allowed
        assert guard.check(Reading(61, later), later).allowed

    def test_stops_when_the_battery_drops_too_fast(self):
        guard = self.guard()
        assert guard.check(Reading(95, NOW), NOW).allowed
        later = NOW + timedelta(hours=10)
        verdict = guard.check(Reading(75, later), later)
        assert not verdict.allowed
        assert "fast" in verdict.reason

    def test_listening_windows(self):
        windows = (config.parse_window("05:30-08:30"),)
        assert window_verdict(windows, NOW).allowed
        assert not window_verdict(windows, NOW.replace(hour=12)).allowed
        assert window_verdict((), NOW).allowed

    def test_daylight(self):
        assert daylight_verdict("above_horizon").allowed
        assert daylight_verdict("below_horizon").reason == "outside daylight"
        unknown = daylight_verdict(None)
        assert not unknown.allowed
        assert unknown.reason.startswith("paused:")

    def test_battery_pauses_are_labelled_clearly(self):
        guard = self.guard()
        reasons = [
            guard.check(Reading(None, None), NOW).reason,
            guard.check(Reading(30, NOW), NOW).reason,
        ]
        assert all(r.startswith("paused: battery") for r in reasons)

    def test_weather(self):
        assert not weather_verdict(30, 0, 25).allowed
        assert not weather_verdict(5, 0.4, 25).allowed
        assert weather_verdict(None, None, 25).allowed


class TestMqtt:
    def test_discovery_covers_entities_and_event(self):
        messages = discovery_messages([("camera_1", "Camera 1")])
        topics = {m.topic for m in messages}
        assert "homeassistant/event/mouflon_population/bird_detected/config" in topics
        assert "homeassistant/sensor/mouflon_population/last_bird/config" in topics
        assert (
            "homeassistant/binary_sensor/mouflon_population/camera_1_listening/config"
            in topics
        )
        for m in messages:
            payload = json.loads(m.payload)
            assert m.retain
            assert payload["unique_id"].startswith("mouflon_population_")
            assert payload["device"]["identifiers"] == ["mouflon_population"]

    def test_bird_event_carries_the_log_fields_only(self):
        sent = []

        class Recorder:
            def publish(self, topic, payload, retain=False):
                sent.append((topic, json.loads(payload)))

        entry = LoggedDetection(NOW, "Camera 1", "Parus major", "Great Tit", 0.8)
        Publisher(Recorder()).bird(entry.as_dict(), demo=False)
        topic, payload = sent[0]
        assert topic == "mouflon/event"
        assert payload["event_type"] == "bird_detected"
        assert set(payload) == {
            "event_type",
            "detected_at",
            "source",
            "scientific_name",
            "common_name",
            "confidence",
            "demo",
        }
        assert payload["demo"] is False


def test_home_assistant_state_reading():
    reading = reading_from_state(
        {"state": "87", "last_reported": "2026-05-10T07:00:00+00:00"}
    )
    assert reading.value == 87
    assert reading_from_state({"state": "unavailable"}).value is None


def test_model_fingerprints(tmp_path):
    model = tmp_path / "acoustic-models/v2.4/tf/model-fp16.tflite"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"model")
    expected = fingerprints(tmp_path)
    assert verify(tmp_path, expected) == []
    model.write_bytes(b"tampered")
    assert verify(tmp_path, expected) == [
        "fingerprint mismatch: acoustic-models/v2.4/tf/model-fp16.tflite"
    ]
    assert verify(tmp_path, {})[0] == "the lock file lists no model files"


def test_preview_escapes_and_counts():
    page = render(
        [
            {
                "detected_at": "2026-05-10T07:00:00",
                "source": "<script>",
                "scientific_name": "Parus major",
                "common_name": "Great Tit",
                "confidence": 0.8,
            }
        ],
        "Birds",
    )
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "1 espèces, 1 détections" in page


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_stream_source_reads_windows_with_ffmpeg_then_reports_the_end():
    example = Path(__file__).resolve().parents[2] / "app/example/soundscape-60s.flac"
    source = StreamSource("file stream", str(example))
    stop = threading.Event()
    windows = []

    def consume():
        windows.extend(window.shape for window in source.windows(stop))

    with pytest.raises(SourceError, match="stream ended"):
        consume()
    assert windows == [(WINDOW_SAMPLES,)] * 20


def test_committed_preview_matches_the_sample_data():
    root = Path(__file__).resolve().parents[2]
    data = json.loads(
        (root / "app/samples/detections.json").read_text(encoding="utf-8")
    )
    expected = render(
        data["detections"],
        "Mouflon Population — aperçu (données d'exemple)",
        data["note"],
    )
    assert (root / "docs/preview/index.html").read_text(encoding="utf-8") == expected


def test_home_location_can_come_from_the_environment(monkeypatch):
    from mouflon_population.ha import HomeAssistant

    monkeypatch.setenv("MOUFLON_HOME_LATITUDE", "50.85")
    monkeypatch.setenv("MOUFLON_HOME_LONGITUDE", "4.35")
    location = HomeAssistant(token="").home_location()
    assert (location.latitude, location.longitude) == (50.85, 4.35)
