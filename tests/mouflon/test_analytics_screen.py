import csv
import json
import random
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from mouflon_population import config, screen, vintage
from mouflon_population.analytics import AnalyticsRow, AnalyticsStore
from mouflon_population.birdlog import BirdLog, LoggedDetection
from mouflon_population.demo import DemoRunner
from mouflon_population.detector import FilteringDetector
from mouflon_population.gallery import Gallery
from mouflon_population.mqtt_publisher import Publisher, discovery_messages
from mouflon_population.service import Service
from PIL import Image

NOW = datetime(2026, 5, 10, 7, 0, tzinfo=UTC)


def _jpeg(image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


EXAMPLE = Path(__file__).resolve().parents[2] / "app/example/soundscape-60s.flac"


class Recorder:
    def __init__(self):
        self.messages = []
        self.subscriptions = {}

    def publish(self, topic, payload, retain=False):
        self.messages.append((topic, payload, retain))

    def subscribe(self, topic, callback):
        self.subscriptions[topic] = callback


class Home:
    def state(self, entity_id):
        raise AssertionError("not used")

    def raw_state(self, entity_id):
        return "above_horizon"

    def home_location(self):
        return None


def row(status="confirmed", when=NOW):
    return AnalyticsRow(
        detected_at=when,
        scientific_name="Parus major",
        common_name="Great Tit",
        confidence=0.81,
        source="Camera 1",
        garden_rarity="regular",
        regional_rarity="usual",
        iucn="LC",
        status=status,
        app_version="0.3.0",
        model_version="BirdNET 2.4 TFLite fp16",
    )


def make_service(tmp_path, raw, analytics, predict):
    settings = config.from_dict(raw, tmp_path / "data")
    transport = Recorder()
    service = Service(
        settings,
        FilteringDetector(predict, settings.min_confidence),
        Publisher(transport),
        BirdLog(settings.data_dir / "birdlog.sqlite", retention_days=1),
        Home(),
        EXAMPLE,
        clock=lambda: NOW,
        guard_interval_s=0.05,
        realtime_replay=False,
        analytics=analytics,
        export_dir=tmp_path / "exports",
    )
    return service, transport


class TestAnalytics:
    def test_schema_keeps_periods_and_versions(self, tmp_path):
        store = AnalyticsStore(tmp_path / "a.sqlite")
        store.add(row())
        target, rows = store.export_csv(tmp_path / "out", NOW)
        assert rows == 1
        with target.open() as f:
            line = next(csv.DictReader(f))
        assert line["year"] == "2026"
        assert line["month"] == "5"
        assert line["week"] == "18"
        assert line["status"] == "confirmed"
        assert line["model_version"].startswith("BirdNET")

    def test_only_final_statuses_are_accepted(self, tmp_path):
        store = AnalyticsStore(tmp_path / "a.sqlite")
        store.add(row("withdrawn"))
        with pytest.raises(ValueError, match="unexpected status"):
            store.add(row("provisional"))
        assert store.count("confirmed") == 0
        assert store.count("withdrawn") == 1

    def test_bird_log_retention_never_touches_analytics(self, tmp_path):
        analytics = AnalyticsStore(tmp_path / "a.sqlite")
        old = NOW - timedelta(days=900)
        analytics.add(row(when=old))
        log = BirdLog(tmp_path / "log.sqlite", retention_days=1)
        log.add(LoggedDetection(old, "Camera 1", "Parus major", "Great Tit", 0.8))
        assert log.purge(NOW) == 1
        assert analytics.count() == 1

    def test_real_confirmed_detections_are_recorded_and_exported(self, tmp_path):
        analytics = AnalyticsStore(tmp_path / "a.sqlite")
        raw = {"test_mode": False, "sources": []}
        service, transport = make_service(
            tmp_path, raw, analytics, lambda _w: [("Parus major_Great Tit", 0.9)]
        )
        source = config.SourceConfig(name="Camera 1", type="rtsp", url="rtsp://h/1")
        window = np.zeros(3, dtype="float32")
        service.handle_window(source, window)
        assert analytics.count() == 0  # first-ever: waits for confirmation
        service.handle_window(source, window)
        assert analytics.count("confirmed") == 2
        service.announce()
        transport.subscriptions["mouflon/command/export_analytics"]()
        exports = list((tmp_path / "exports").glob("bird-analytics-*.csv"))
        assert len(exports) == 1
        export = [
            json.loads(p)
            for t, p, _ in transport.messages
            if t == "mouflon/analytics_export"
        ]
        assert export[-1]["rows"] == 2

    def test_test_mode_never_enters_analytics(self, tmp_path):
        analytics = AnalyticsStore(tmp_path / "a.sqlite")
        service, _ = make_service(
            tmp_path,
            {"test_mode": True},
            analytics,
            lambda _w: [("Turdus merula_Eurasian Blackbird", 0.9)],
        )
        stop = threading.Event()
        thread = threading.Thread(target=service.run, args=(stop,))
        thread.start()
        while len(service.birdlog.recent()) < 3:
            threading.Event().wait(0.02)
        stop.set()
        thread.join(timeout=10)
        assert analytics.count() == 0

    def test_demo_mode_never_enters_analytics(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mouflon_population.demo.PEAK_PER_MINUTE", 60_000)
        analytics = AnalyticsStore(tmp_path / "a.sqlite")
        settings = config.from_dict({"demo_mode": True, "test_mode": False}, tmp_path)
        demo = DemoRunner(
            settings,
            Publisher(Recorder()),
            Home(),
            rng=random.Random(3),
            clock=lambda: NOW,
            tick_s=60,
        )
        assert sum(len(demo.tick()) for _ in range(3)) > 0
        assert analytics.count() == 0
        assert not hasattr(demo, "analytics")


class TestScreen:
    @pytest.mark.parametrize("size", [(480, 800), (1200, 1600)])
    def test_views_render_at_the_configured_size(self, size):
        bird = screen.Bird(
            "Mésange charbonnière",
            "Parus major",
            "2026-05-10T07:42:00",
            "Camera 1",
            3,
            ("Nouveau pour le jardin",),
        )
        assert screen.render_last_bird(bird, size).size == size
        assert screen.render_today([bird] * 4, NOW, size, total=9).size == size
        assert screen.render_last_bird(None, size).size == size
        assert screen.render_collage(bird, [bird] * 9, NOW, size).size == size

    def test_the_frame_never_shows_the_source_name(self, monkeypatch):
        drawn = []
        original = screen.ImageDraw.ImageDraw.text

        def spy(self, xy, text, *args, **kwargs):
            drawn.append(text)
            return original(self, xy, text, *args, **kwargs)

        monkeypatch.setattr(screen.ImageDraw.ImageDraw, "text", spy)
        bird = screen.Bird(
            "Merle noir", "Turdus merula", "2026-05-10T07:42:00", "Camera 1"
        )
        screen.render_collage(bird, [bird], NOW, (480, 800))
        screen.render_last_bird(bird, (480, 800))
        screen.render_today([bird], NOW, (480, 800))
        assert drawn
        assert not any("Camera 1" in text for text in drawn)
        assert any("entendu à" in text for text in drawn)  # French by default

    def test_a_provisional_bird_reads_confirmation_in_progress(self, monkeypatch):
        drawn = []
        original = screen.ImageDraw.ImageDraw.text

        def spy(self, xy, text, *args, **kwargs):
            drawn.append(text)
            return original(self, xy, text, *args, **kwargs)

        monkeypatch.setattr(screen.ImageDraw.ImageDraw, "text", spy)
        bird = screen.bird_from_dict(
            {
                "common_name": "Huppe fasciée",
                "scientific_name": "Upupa epops",
                "status": "provisional",
                "detected_at": "2026-05-10T07:42:00",
            }
        )
        screen.render_last_bird(bird, (480, 800))
        assert any("Confirmation en cours" in text for text in drawn)
        assert not any("À confirmer" in text for text in drawn)

    def test_eink_pages_use_exact_palette_colours_for_figures(self):
        bird = screen.Bird("Merle noir", "Turdus merula")
        page = screen.render_last_bird(bird, (240, 400), paper=screen.EINK_PAPER)
        colours = {c for _, c in page.getcolors(1 << 16)}
        assert screen.EINK_PALETTE[1] in colours  # paper speckle
        assert screen.EINK_PALETTE[0] in colours  # silhouette and text

    def test_eink_paper_is_a_calm_speckle_of_palette_colours(self):
        sheet = screen.paper_sheet((240, 400), screen.EINK_PAPER)
        counts = {c: n for n, c in sheet.getcolors(1 << 16)}
        inks = {screen.EINK_PALETTE[i] for i in screen.EINK_PAPER_INKS}
        assert set(counts) <= inks
        # No black, blue or green dots: the small names stay readable.
        assert screen.EINK_PALETTE[0] not in counts
        assert counts[screen.EINK_PALETTE[1]] > 0.7 * 240 * 400
        # Same speckle on every refresh.
        assert (
            sheet.tobytes()
            == screen.paper_sheet((240, 400), screen.EINK_PAPER).tobytes()
        )

    def test_screen_paper_is_aged_taupe(self):
        page = screen.render_last_bird(None, (240, 400))
        assert page.getpixel((2, 2)) == vintage.PAPER
        r, g, b = vintage.PAPER
        assert r > g > b  # warm
        assert r < 230  # clearly not white

    def test_plates_are_printed_without_a_rectangle(self):
        plate = Image.new("RGB", (300, 400), (60, 90, 40))  # painted to the edge
        bird = screen.Bird(
            "Merle noir", "Turdus merula", image=_jpeg(plate), heard_at="x"
        )
        page = screen.render_last_bird(bird, (240, 400))
        # The page border stays plain paper all round: the plate dissolves first.
        for x in range(0, 240, 7):
            assert page.getpixel((x, 1)) == vintage.PAPER
        for y in range(0, 300, 7):
            assert page.getpixel((1, y)) == vintage.PAPER
            assert page.getpixel((238, y)) == vintage.PAPER

    def test_birds_without_a_plate_are_line_sketches_not_flat_shapes(self):
        sketch = screen.silhouette("Streptopelia decaocto", (200, 200))
        alpha = sketch.getchannel("A")
        inked = sum(1 for v in alpha.get_flattened_data() if v > 0)
        assert 0 < inked < 0.12 * 200 * 200  # outline and strokes only
        colours = {c[:3] for _, c in sketch.getcolors(1 << 16) if c[3] > 0}
        assert colours == {screen.SEPIA}  # warm sepia pen, not grey

    def test_a_full_page_keeps_every_bird(self):
        birds = [screen.Bird(f"Oiseau {i}", f"Avis {i}") for i in range(10)]
        area = (29, 32, 451, 672)
        for day in range(1, 29):
            seed = screen.seed_for(f"2026-05-{day:02d}")
            assert len(screen.place(birds, area, seed, True)) == 10
            assert len(screen.place(birds, area, seed, False)) == 10

    def test_preview_page_has_french_controls_for_every_page(self, tmp_path):
        sample = Path(__file__).resolve().parents[2] / "app/samples/detections.json"
        screen.write_preview(sample, tmp_path, "240x400", None, "fr")
        html = (tmp_path / "preview.html").read_text(encoding="utf-8")
        for word in ("Vue", "Taille", "Rendu", "Collage unique", "Oiseaux du jour"):
            assert word in html
        assert html.count("data-key=") == 6  # 3 views x normal/e-ink
        assert len(list(tmp_path.glob("*.png"))) == 6
        assert "http" not in html.replace("http-equiv", "")  # nothing fetched

    def test_watch_follows_renderer_fonts_and_sample(self, tmp_path):
        sample = tmp_path / "detections.json"
        files = screen.watched_files(sample)
        assert Path(screen.__file__).resolve() in files
        assert sample in files
        assert any(p.suffix == ".ttf" for p in files)

    def test_eink_preview_uses_only_the_panel_palette(self):
        image = screen.render_last_bird(None, (240, 400))
        colours = {c for _, c in screen.eink(image).getcolors(1 << 16)}
        assert colours <= set(screen.EINK_PALETTE)

    def test_gallery_refreshes_the_screen_slowly(self, tmp_path):
        transport = Recorder()
        gallery = Gallery(Publisher(transport), None, (240, 400), screen_refresh_s=600)
        gallery.enrich({"scientific_name": "Parus major", "common_name": "Great Tit"})
        assert gallery.render_screen_if_due(NOW)
        gallery.enrich({"scientific_name": "Parus major", "common_name": "Great Tit"})
        assert not gallery.render_screen_if_due(NOW + timedelta(minutes=5))
        assert gallery.render_screen_if_due(NOW + timedelta(minutes=11))
        pngs = [
            p for t, p, _ in transport.messages if t == "mouflon/image/screen_last_bird"
        ]
        assert len(pngs) == 2
        assert Image.open(__import__("io").BytesIO(pngs[0])).size == (240, 400)
        assert any(t == "mouflon/image/screen" for t, _, _ in transport.messages)

    def test_alternate_view_turns_pages_at_each_refresh(self):
        transport = Recorder()
        gallery = Gallery(Publisher(transport), None, (240, 400), 600, "alternate")
        gallery.enrich({"scientific_name": "Parus major", "common_name": "Mésange"})
        assert gallery.render_screen_if_due(NOW)
        assert gallery.render_screen_if_due(NOW + timedelta(minutes=11))
        frames = [p for t, p, _ in transport.messages if t == "mouflon/image/screen"]
        assert len(frames) == 2
        assert frames[0] != frames[1]


def test_discovery_has_export_button_and_screen_images():
    topics = {m.topic for m in discovery_messages([])}
    assert "homeassistant/button/mouflon_population/export_analytics/config" in topics
    assert "homeassistant/image/mouflon_population/screen_last_bird/config" in topics
    assert "homeassistant/image/mouflon_population/screen_today/config" in topics


def test_entities_are_named_in_french_with_fixed_ids():
    configs = {
        m.topic: json.loads(m.payload)
        for m in discovery_messages([("camera_1", "Camera 1")])
    }
    last = configs["homeassistant/sensor/mouflon_population/last_bird/config"]
    assert last["name"] == "Dernier oiseau"
    assert last["default_entity_id"] == "sensor.mouflon_population_last_bird"
    screen_cfg = configs["homeassistant/image/mouflon_population/screen/config"]
    assert screen_cfg["name"] == "Écran"
    status = configs["homeassistant/sensor/mouflon_population/camera_1_status/config"]
    assert status["name"] == "État de Camera 1"


def test_rarity_levels_have_on_off_sensors_for_the_dashboard():
    topics = {m.topic for m in discovery_messages([])}
    for level in ("garden", "regional", "global"):
        topic = f"homeassistant/binary_sensor/mouflon_population/rarity_{level}/config"
        assert topic in topics


def test_source_statuses_are_shown_in_french():
    from mouflon_population import i18n

    assert i18n.status_text("listening") == "à l'écoute"
    assert i18n.status_text("paused: battery low (18 %)") == (
        "en pause : batterie faible (18 %)"
    )
    assert i18n.status_text("something new") == "something new"
    transport = Recorder()
    Publisher(transport).source_status("camera_1", "listening")
    assert ("mouflon/source/camera_1/listening", "ON", True) in transport.messages
    assert ("mouflon/source/camera_1/status", "à l'écoute", True) in transport.messages


def test_provisional_status_words():
    from mouflon_population import i18n

    assert i18n.STATUS_WORDS["fr"]["provisional"] == "Confirmation en cours"
    assert i18n.STATUS_WORDS["en"]["provisional"] == "Confirmation in progress"


def test_french_is_the_default_language(tmp_path):
    settings = config.from_dict({}, tmp_path)
    assert settings.language == "fr"
    assert settings.screen_view == "collage"


def test_screen_size_setting(tmp_path):
    assert config.from_dict({"screen_size": "800x1280"}, tmp_path).screen_size == (
        800,
        1280,
    )
    with pytest.raises(config.ConfigError):
        config.from_dict({"screen_size": "big"}, tmp_path)
