import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from mouflon_population import config, i18n, vintage
from mouflon_population.birdlog import BirdLog, LoggedDetection
from mouflon_population.gallery import Gallery
from mouflon_population.library import Library
from mouflon_population.mqtt_publisher import Publisher, discovery_messages
from mouflon_population.rarity import (
    Confirmer,
    Observation,
    assess,
    garden_level,
    regional_level,
)
from PIL import Image

NOW = datetime(2026, 5, 10, 7, 0, tzinfo=UTC)


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    (root / "images").mkdir(parents=True)
    (root / "songs").mkdir()
    (root / "images" / "turdus_merula.jpg").write_bytes(b"\xff\xd8blackbird")
    (root / "songs" / "turdus_merula.mp3").write_bytes(b"ID3song")
    catalogue = {
        "Turdus merula": {
            "common_name": "Eurasian Blackbird",
            "image": "turdus_merula.jpg",
            "credit": "Naumann, Band I, Tafel 1. Public domain, via Wikimedia Commons.",
            "iucn": "LC",
            "song": "turdus_merula.mp3",
            "song_credit": "A. Recordist, xeno-canto XC1, CC BY-SA 4.0",
        },
        "Streptopelia turtur": {"common_name": "European Turtle-Dove", "iucn": "VU"},
    }
    (root / "catalogue.json").write_text(json.dumps({"species": catalogue}))
    return Library(root)


class Recorder:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, retain=False):
        self.messages.append((topic, payload, retain))

    def last(self, topic):
        return [p for t, p, _ in self.messages if t == topic][-1]


class TestRarity:
    def test_garden_levels(self):
        assert garden_level(True, 0, 3) == "new"
        assert garden_level(False, 2, 3) == "rare"
        assert garden_level(False, 3, 3) == "regular"

    def test_regional_level(self):
        assert regional_level(0.04, 0.1) == "unusual"
        assert regional_level(0.5, 0.1) == "usual"
        assert regional_level(None, 0.1) == "unknown"

    def test_tags_have_a_label_icon_colour_and_short_label_per_level(self):
        rarity = assess("new", "unusual", "NT").as_dict()
        assert rarity["labels"] == [
            "Nouveau pour le jardin",
            "Inhabituel en Belgique",
            "Quasi menacé",
        ]
        for tag in rarity["tags"]:
            assert tag["icon"].startswith("mdi:")
            assert tag["color"]
            assert len(tag["short"]) <= 12
        assert not assess("regular", "usual", "LC").is_rare

    def test_a_rare_candidate_needs_two_confident_detections(self):
        confirmer = Confirmer(0.75, timedelta(minutes=15))
        assert (
            confirmer.observe("Upupa epops", Observation(NOW, "Camera 1", 0.95)) == []
        )
        later = NOW + timedelta(minutes=20)
        assert (
            confirmer.observe("Upupa epops", Observation(later, "Camera 1", 0.9)) == []
        )
        weak = later + timedelta(minutes=1)
        assert (
            confirmer.observe("Upupa epops", Observation(weak, "Camera 1", 0.6)) == []
        )
        other = later + timedelta(minutes=2)
        confirmed = confirmer.observe(
            "Upupa epops", Observation(other, "Camera 2", 0.8)
        )
        assert [o.source for o in confirmed] == ["Camera 1", "Camera 2"]


class TestLibrary:
    def test_entries_images_and_songs(self, library, tmp_path):
        entry = library.get("Turdus merula")
        assert entry.credit.startswith("Naumann")
        assert library.image_bytes("Turdus merula") == b"\xff\xd8blackbird"
        assert library.image_bytes("Streptopelia turtur") is None
        assert library.song_media_id("Turdus merula") == (
            "media-source://media_source/local/mouflon_population/songs/turdus_merula.mp3"
        )
        media = tmp_path / "media"
        assert library.install_songs(media) == 1
        assert (media / "songs" / "turdus_merula.mp3").read_bytes() == b"ID3song"
        assert library.install_songs(media) == 0
        assert sorted(p.name for p in media.rglob("*") if p.is_file()) == [
            "turdus_merula.mp3"
        ]


class TestGallery:
    def test_last_bird_and_species_list(self, library):
        transport = Recorder()
        gallery = Gallery(Publisher(transport), library)
        detection = gallery.enrich(
            {"scientific_name": "Turdus merula", "common_name": "Eurasian Blackbird"}
        )
        assert detection["image"] == "image.mouflon_population_last_bird_drawing"
        assert detection["credit"].startswith("Naumann")
        assert detection["song"].endswith("turdus_merula.mp3")

        gallery.show_last("Turdus merula")
        assert transport.last("mouflon/image/last_bird_drawing") == b"\xff\xd8blackbird"

        species = [
            {
                "scientific_name": "Streptopelia turtur",
                "common_name": "European Turtle-Dove",
                "count": 1,
                "last_heard": NOW.isoformat(),
            },
            {
                "scientific_name": "Turdus merula",
                "common_name": "Eurasian Blackbird",
                "count": 4,
                "last_heard": (NOW - timedelta(minutes=5)).isoformat(),
            },
        ]
        rarity = {"Streptopelia turtur": assess("rare", "usual", "VU").as_dict()}
        gallery.show_species(species, rarity)
        items = json.loads(transport.last("mouflon/species_today"))["species"]
        assert [i["common_name"] for i in items] == [
            "European Turtle-Dove",
            "Eurasian Blackbird",
        ]
        assert items[0]["image"] is None
        assert items[0]["rarity"]["labels"] == ["Rare au jardin", "Vulnérable"]
        assert items[1]["image"] == "image.mouflon_population_today_2_drawing"
        placeholder = transport.last("mouflon/image/today_1_drawing")
        assert placeholder.startswith(b"\xff\xd8")  # drawn "Gravure à venir" card
        assert Image.open(io.BytesIO(placeholder)).getpixel((3, 3)) == pytest.approx(
            vintage.PAPER, abs=4
        )
        assert transport.last("mouflon/image/today_2_drawing") == b"\xff\xd8blackbird"

    def test_discovery_has_image_entities_rare_event_and_species_attributes(self):
        configs = {m.topic: json.loads(m.payload) for m in discovery_messages([])}
        prefix = "homeassistant"
        assert f"{prefix}/event/mouflon_population/rare_bird/config" in configs
        image = configs[f"{prefix}/image/mouflon_population/last_bird_drawing/config"]
        assert image["content_type"] == "image/jpeg"
        for n in range(1, 7):
            assert (
                f"{prefix}/image/mouflon_population/today_{n}_drawing/config" in configs
            )
        species = configs[f"{prefix}/sensor/mouflon_population/species_today/config"]
        assert species["json_attributes_topic"] == "mouflon/species_today"


def test_species_list_is_capped_and_most_recent_first(tmp_path):
    log = BirdLog(tmp_path / "log.sqlite")
    for minute in range(40):
        name = f"Species {minute:02d}"
        log.add(
            LoggedDetection(
                NOW + timedelta(minutes=minute), "Camera 1", name, name, 0.8
            )
        )
    species = log.day_species(NOW)
    assert len(species) == 30
    assert species[0]["scientific_name"] == "Species 39"


def test_bird_log_history_for_garden_rarity(tmp_path):
    log = BirdLog(tmp_path / "log.sqlite")
    assert log.history("Parus major", NOW - timedelta(days=365)) == (True, 0)
    for days_ago in (1, 1, 30, 400):
        when = NOW - timedelta(days=days_ago)
        log.add(LoggedDetection(when, "Camera 1", "Parus major", "Great Tit", 0.8))
    assert log.history("Parus major", NOW - timedelta(days=365)) == (False, 2)


def test_rarity_settings_are_validated(tmp_path):
    with pytest.raises(config.ConfigError):
        config.from_dict({"rare_min_confidence": 0.3, "min_confidence": 0.5}, tmp_path)


def test_placeholder_text_is_french_by_default_and_from_i18n():
    i18n.configure("fr")
    assert i18n.t("drawing_to_come") == "Gravure à venir"
    i18n.configure("en")
    assert i18n.t("drawing_to_come") == "Drawing to come"
    i18n.configure("fr")


def test_drawings_are_printed_on_aged_paper_with_a_soft_edge():
    plate = Image.new("RGB", (200, 260), (250, 250, 248))  # white plate paper
    plate.paste((40, 40, 40), (60, 80, 140, 180))  # the "bird"
    buffer = io.BytesIO()
    plate.save(buffer, "JPEG")
    out = Image.open(io.BytesIO(vintage.rendition(buffer.getvalue(), "Avis")))
    assert out.width > plate.width  # soft bleed all round
    assert out.height > plate.height
    corner = out.getpixel((2, 2))
    assert corner == pytest.approx(vintage.PAPER, abs=4)  # no white anywhere
    middle = out.getpixel((out.width // 2, out.height // 2))
    assert max(middle) < 80  # the drawing itself is kept


def test_unreadable_drawings_pass_through_unchanged():
    assert vintage.rendition(b"\xff\xd8not a jpeg", "x") == b"\xff\xd8not a jpeg"


def test_organic_edge_is_zero_on_every_border_and_irregular():
    mask = vintage.organic_mask((300, 400), seed=7, band=40)
    width, height = mask.size
    border = [mask.getpixel((x, 0)) for x in range(width)]
    border += [mask.getpixel((x, height - 1)) for x in range(width)]
    border += [mask.getpixel((0, y)) for y in range(height)]
    border += [mask.getpixel((width - 1, y)) for y in range(height)]
    assert max(border) <= 2
    assert mask.getpixel((150, 200)) == 255

    # Where the edge reaches half strength differs along a side: no straight line.
    def depth(y):
        return next(x for x in range(width) if mask.getpixel((x, y)) >= 128)

    depths = {depth(y) for y in range(80, 320, 10)}
    assert max(depths) - min(depths) >= 6
