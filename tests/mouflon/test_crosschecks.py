"""Confirmation cross-checks: Perch second opinion (MOUL-54) and local GBIF
statistics (MOUL-55)."""

import gc
import json
import os
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from mouflon_population import SAMPLE_RATE, config, models
from mouflon_population import second_opinion as so
from mouflon_population.birdlog import BirdLog
from mouflon_population.detector import FilteringDetector
from mouflon_population.local_check import WEEKS, LocalObservations
from mouflon_population.mqtt_publisher import Publisher
from mouflon_population.rarity import ConfirmationTracker, Observation, assess
from mouflon_population.service import Service

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "app/example/soundscape-60s.flac"
CROSSCHECK = ROOT / "app/crosscheck"
START = datetime(2026, 5, 10, 7, 0, tzinfo=UTC)  # BirdNET week 18
WINDOW = 15


def tracker(local="observed"):
    return ConfirmationTracker(
        0.75, timedelta(minutes=WINDOW), local_lookup=lambda _s, _w: local
    )


def seen(confidence, minutes=0):
    return Observation(START + timedelta(minutes=minutes), "Camera 1", confidence)


RARE = assess("new", "usual", None)


# --- the rule: two of four checks -------------------------------------------------


class TestRule:
    def test_confident_and_observed_locally_confirms_at_once(self):
        state, _ = tracker().observe("Upupa epops", "Huppe", RARE, seen(0.9))
        assert state == "confirmed"

    def test_rarely_observed_needs_a_second_acoustic_check(self):
        t = tracker("rare")
        state, entry = t.observe("Upupa epops", "Huppe", RARE, seen(0.9))
        assert state == "provisional"
        assert t.progress(entry) == 50
        assert t.record_perch(entry, "agree") == "confirmed"

    def test_rarely_observed_confident_then_heard_again_confirms(self):
        t = tracker("rare")
        t.observe("Upupa epops", "Huppe", RARE, seen(0.9))
        state, _ = t.observe("Upupa epops", "Huppe", RARE, seen(0.6, 5))
        assert state == "confirmed"

    def test_uncertain_and_observed_locally_waits_for_one_more_check(self):
        t = tracker()
        state, entry = t.observe("Parus major", "Mésange", RARE, seen(0.6))
        assert state == "provisional"
        assert t.record_perch(entry, "disagree") == "provisional"
        state, _ = t.observe("Parus major", "Mésange", RARE, seen(0.55, 3))
        assert state == "confirmed"

    def test_uncertain_rare_with_only_perch_is_not_enough(self):
        t = tracker("rare")
        _, entry = t.observe("Upupa epops", "Huppe", RARE, seen(0.6))
        assert t.record_perch(entry, "agree") == "provisional"
        assert t.progress(entry) == 50

    def test_skipped_checks_never_block(self):
        t = tracker("skipped:unavailable")
        _, entry = t.observe("Upupa epops", "Huppe", RARE, seen(0.9))
        assert t.record_perch(entry, "skipped:busy") == "provisional"
        state, _ = t.observe("Upupa epops", "Huppe", RARE, seen(0.9, 4))
        assert state == "confirmed"

    def test_unconfirmed_bird_is_withdrawn_when_the_window_ends(self):
        t = tracker("rare")
        t.observe("Upupa epops", "Huppe", RARE, seen(0.6))
        expired = t.expire(START + timedelta(minutes=WINDOW + 1))
        assert [e.scientific for e in expired] == ["Upupa epops"]
        assert t.pending == {}

    def test_a_later_skip_keeps_an_earlier_disagreement(self):
        t = tracker("rare")
        _, entry = t.observe("Upupa epops", "Huppe", RARE, seen(0.6))
        t.record_perch(entry, "disagree")
        t.record_perch(entry, "skipped:busy")
        assert entry.perch == "disagree"

    def test_steps_are_four_in_french_with_states_and_notes(self):
        t = tracker("rare")
        _, entry = t.observe("Upupa epops", "Huppe", RARE, seen(0.9))
        t.record_perch(entry, "skipped:busy")
        steps = t.steps(entry)
        assert [s["key"] for s in steps] == ["confident", "again", "perch", "local"]
        assert [s["state"] for s in steps] == ["done", "pending", "skipped", "failed"]
        assert steps[2]["name"] == "Deuxième avis (Perch) concordant"
        assert steps[2]["note"] == "Pi occupé, vérification passée"
        assert steps[3]["name"] == "Observé localement à cette période"
        assert steps[3]["note"] == "rarement observé en Belgique à cette période"
        assert [s["done"] for s in steps] == [True, False, False, False]


# --- Perch, with a fake ONNX session -----------------------------------------------


LABELS = ["Turdus merula", "Upupa epops", "Coloeus monedula"] + [
    f"Genus species{i}" for i in range(so.PERCH_CLASSES - 3)
]


class FakeSession:
    def __init__(self, logits):
        self.logits = logits
        self.inputs = []

    def run(self, outputs, feeds):
        assert outputs == ["label"]
        self.inputs.append(feeds["inputs"].shape)
        row = np.full(so.PERCH_CLASSES, -8.0, dtype=np.float32)
        for index, value in self.logits.items():
            row[index] = value
        return [row[None, :]]


def perch_dir(tmp_path, labels=LABELS):
    folder = tmp_path / "perch"
    folder.mkdir()
    (folder / so.MODEL_FILE).write_bytes(b"x" * 1024)
    (folder / so.LABELS_FILE).write_text("inat2024_fsd50k\n" + "\n".join(labels))
    return folder


def opinion(tmp_path, logits, **kwargs):
    session = FakeSession(logits)
    result = so.SecondOpinion(
        perch_dir(tmp_path),
        aliases={"Corvus monedula": "Coloeus monedula"},
        session_factory=lambda _p: session,
        memory=kwargs.get("memory", lambda: 4000.0),
        load=kwargs.get("load", lambda: 0.1),
    )
    result.load_model()
    return result, session


WINDOW_AUDIO = np.zeros(3 * SAMPLE_RATE, dtype=np.float32)
NOISE = (np.random.default_rng(0).standard_normal(3 * SAMPLE_RATE) * 1e-3).astype(
    np.float32
)


class TestPerch:
    def test_prepare_resamples_three_seconds_and_repeats_to_five(self):
        tone = np.sin(np.linspace(0, 3000, 3 * SAMPLE_RATE)).astype(np.float32)
        prepared = so.prepare(tone)
        assert prepared.shape == (1, so.PERCH_SAMPLES)
        assert prepared.dtype == np.float32
        assert np.abs(prepared[0, 100_000:]).max() > 0.5  # no silent tail
        np.testing.assert_array_equal(prepared[0, 96_000:100_000], prepared[0, :4000])

    def test_digital_silence_is_never_sent_to_perch(self, tmp_path):
        perch, session = opinion(tmp_path, {1: 11.0})
        assert perch.ask(WINDOW_AUDIO, "Upupa epops").verdict == "skipped:silence"
        assert session.inputs == []

    def test_agrees_on_a_high_score(self, tmp_path):
        perch, session = opinion(tmp_path, {1: 11.0})
        result = perch.ask(NOISE, "Upupa epops")
        assert result.verdict == "agree"
        assert result.score > 0.8
        assert session.inputs == [(1, so.PERCH_SAMPLES)]

    def test_a_top_rank_with_a_low_logit_is_not_agreement(self, tmp_path):
        # Noise reaches logits of about 7 for some species: top rank means nothing.
        perch, _ = opinion(tmp_path, {1: 7.0})
        result = perch.ask(NOISE, "Upupa epops")
        assert result.verdict == "disagree"
        assert result.score < 0.5

    def test_disagrees_when_it_hears_something_else(self, tmp_path):
        perch, _ = opinion(tmp_path, {0: 3.0, 2: 3.0, 5: 3.0, 1: -6.0})
        assert perch.ask(NOISE, "Upupa epops").verdict == "disagree"

    def test_taxonomy_alias_by_scientific_name(self, tmp_path):
        perch, _ = opinion(tmp_path, {2: 11.0})
        assert perch.ask(NOISE, "Corvus monedula").verdict == "agree"

    def test_unknown_species_is_skipped(self, tmp_path):
        perch, _ = opinion(tmp_path, {})
        verdict = perch.ask(NOISE, "Avis inexistens").verdict
        assert verdict == "skipped:unknown_species"

    def test_busy_pi_is_skipped(self, tmp_path):
        perch, session = opinion(tmp_path, {1: 11.0}, load=lambda: 3.0)
        assert perch.ask(NOISE, "Upupa epops").verdict == "skipped:busy"
        assert session.inputs == []

    def test_one_opinion_at_a_time(self, tmp_path):
        perch, _ = opinion(tmp_path, {1: 11.0})
        with perch._lock:
            assert perch.ask(NOISE, "Upupa epops").verdict == "skipped:busy"

    def test_not_enough_memory_skips_loading(self, tmp_path):
        perch, _ = opinion(tmp_path, {1: 11.0}, memory=lambda: 100.0)
        assert not perch.ready
        assert perch.ask(NOISE, "Upupa epops").verdict == "skipped:memory"

    def test_missing_files_and_wrong_labels_are_skipped(self, tmp_path):
        missing = so.SecondOpinion(tmp_path / "nothing")
        missing.load_model()
        assert missing.ask(NOISE, "Upupa epops").verdict == ("skipped:unavailable")
        wrong = so.SecondOpinion(
            perch_dir(tmp_path, LABELS[:10]),
            session_factory=lambda _p: FakeSession({}),
            memory=lambda: 4000.0,
        )
        wrong.load_model()
        assert wrong.ask(NOISE, "Upupa epops").verdict == "skipped:error"

    def test_rate_limit_puts_silent_checks_last(self, tmp_path, monkeypatch):
        perch, _ = opinion(tmp_path, {1: 11.0})
        for _ in range(so.SILENT_MAX_PER_MINUTE):
            assert perch.ask(NOISE, "Upupa epops").verdict == "agree"
        silent = perch.ask(NOISE, "Upupa epops", silent=True)
        assert silent.verdict == "skipped:busy"
        for _ in range(so.MAX_PER_MINUTE - so.SILENT_MAX_PER_MINUTE):
            assert perch.ask(NOISE, "Upupa epops").verdict == "agree"
        assert perch.ask(NOISE, "Upupa epops").verdict == "skipped:busy"

    def test_silent_checks_skip_first_when_the_pi_is_loaded(self, tmp_path):
        perch, _ = opinion(tmp_path, {1: 11.0}, load=lambda: 1.2)
        assert perch.ask(NOISE, "Upupa epops", silent=True).verdict == ("skipped:busy")
        assert perch.ask(NOISE, "Upupa epops").verdict == "agree"

    def test_still_loading_is_skipped(self):
        perch = so.SecondOpinion(Path("/nonexistent"))
        assert perch.ask(NOISE, "Upupa epops").verdict == "skipped:loading"


# --- the service: same window, only when needed, never kept ------------------------


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


class SpyOpinion:
    def __init__(self, verdict):
        self.verdict = verdict
        self.score = 0.9
        self.status = "ready"
        self.windows = []

    def ask(self, window, scientific, silent=False):
        self.windows.append(id(window))
        return so.Opinion(self.verdict, self.score, 0.1)


def build(tmp_path, label, confidence, verdict="agree", local=None, raw=None):
    settings = config.from_dict(
        {"test_mode": False, "sources": [], **(raw or {})}, tmp_path / "data"
    )
    spy = SpyOpinion(verdict)
    transport = Recorder()
    service = Service(
        settings,
        FilteringDetector(lambda _w: [(label, confidence)], settings.silent_check_min),
        Publisher(transport),
        BirdLog(settings.data_dir / "birdlog.sqlite"),
        Home(),
        EXAMPLE,
        clock=lambda: START,
        second_opinion=spy,
        local_observations=local,
    )
    source = config.SourceConfig(name="Camera 1", type="rtsp", url="rtsp://h/1")
    return service, transport, spy, source


def weekly(species, week_count=1000):
    return LocalObservations(
        {
            "calendar": "birdnet-48",
            "years": [2016, 2025],
            "totals": [100_000] * WEEKS,
            "species": {name: [week_count] * WEEKS for name in species},
            "aliases": {"Corvus monedula": "Coloeus monedula"},
        }
    )


class TestService:
    def test_perch_hears_the_same_window_and_confirms_an_uncertain_bird(self, tmp_path):
        local = weekly(["Turdus merula"])
        service, transport, spy, source = build(
            tmp_path, "Turdus merula_Eurasian Blackbird", 0.6, local=local
        )
        # Seen before, so it is not "new": the only reason to check is uncertainty.
        service.birdlog.history = lambda *_: (False, 200)
        window = np.zeros(WINDOW_AUDIO.shape, dtype=np.float32)
        assert service.handle_window(source, window) == 1
        assert spy.windows == [id(window)]
        last = transport.json("mouflon/last_bird")[-1]
        assert last["status"] == "confirmed"
        states = [s["state"] for s in last["confirmation_steps"]]
        assert states == ["pending", "pending", "done", "done"]

    def test_sure_common_bird_is_confirmed_when_heard_twice_without_perch(
        self, tmp_path
    ):
        service, transport, spy, source = build(
            tmp_path,
            "Turdus merula_Eurasian Blackbird",
            0.9,
            local=weekly(["Turdus merula"]),
        )
        service.birdlog.history = lambda *_: (False, 200)
        assert service.handle_window(source, WINDOW_AUDIO) == 0
        last = transport.json("mouflon/last_bird")[-1]
        assert last["status"] == "provisional"
        assert last["confirmation_progress"] == 50
        assert service.handle_window(source, WINDOW_AUDIO) == 2
        assert transport.json("mouflon/last_bird")[-1]["status"] == "confirmed"
        assert spy.windows == []

    def test_sure_common_bird_at_once_when_the_setting_is_off(self, tmp_path):
        service, transport, spy, source = build(
            tmp_path,
            "Turdus merula_Eurasian Blackbird",
            0.9,
            raw={"common_confirm_twice": False},
        )
        service.birdlog.history = lambda *_: (False, 200)
        assert service.handle_window(source, WINDOW_AUDIO) == 1
        assert spy.windows == []
        assert transport.json("mouflon/last_bird")[-1]["confirmation_steps"] == []

    def test_sure_bird_rarely_observed_locally_is_cross_checked(self, tmp_path):
        local = weekly(["Upupa epops"])  # blackbird absent from the statistics
        service, transport, spy, source = build(
            tmp_path, "Turdus merula_Eurasian Blackbird", 0.9, "disagree", local
        )
        service.birdlog.history = lambda *_: (False, 200)
        assert service.handle_window(source, WINDOW_AUDIO) == 0
        assert len(spy.windows) == 1
        assert transport.json("mouflon/last_bird")[-1]["status"] == "provisional"

    def test_the_unsure_zone_top_is_a_setting(self, tmp_path):
        local = weekly(["Turdus merula"])
        service, _, spy, source = build(
            tmp_path,
            "Turdus merula_Eurasian Blackbird",
            0.65,
            local=local,
            raw={"second_opinion_threshold": 0.6, "common_confirm_twice": False},
        )
        service.birdlog.history = lambda *_: (False, 200)
        assert service.handle_window(source, WINDOW_AUDIO) == 1
        assert spy.windows == []

    def test_silent_threshold_above_publication_is_refused(self, tmp_path):
        with pytest.raises(config.ConfigError, match="silent_check_min"):
            config.from_dict({"silent_check_min": 0.6}, tmp_path)

    def test_unsure_zone_top_below_detection_threshold_is_refused(self, tmp_path):
        with pytest.raises(config.ConfigError, match="second_opinion_threshold"):
            config.from_dict({"second_opinion_threshold": 0.3}, tmp_path)

    def test_confident_first_timer_common_in_belgium_needs_no_perch(self, tmp_path):
        local = weekly(["Upupa epops"])
        service, transport, spy, source = build(
            tmp_path, "Upupa epops_Eurasian Hoopoe", 0.9, local=local
        )
        assert service.handle_window(source, WINDOW_AUDIO) == 1
        assert spy.windows == []
        last = transport.json("mouflon/last_bird")[-1]
        assert last["status"] == "confirmed"
        assert "Nouveau pour le jardin" in last["rarity"]["labels"]

    def test_rarely_observed_first_timer_is_confirmed_by_perch(self, tmp_path):
        local = weekly(["Turdus merula"])
        service, transport, spy, source = build(
            tmp_path, "Upupa epops_Eurasian Hoopoe", 0.9, local=local
        )
        assert service.handle_window(source, WINDOW_AUDIO) == 1
        assert len(spy.windows) == 1
        states = [
            s["state"]
            for s in transport.json("mouflon/last_bird")[-1]["confirmation_steps"]
        ]
        assert states == ["done", "pending", "done", "failed"]

    def test_perch_disagreeing_keeps_the_bird_provisional(self, tmp_path):
        local = weekly(["Turdus merula"])
        service, transport, _, source = build(
            tmp_path, "Upupa epops_Eurasian Hoopoe", 0.9, "disagree", local
        )
        assert service.handle_window(source, WINDOW_AUDIO) == 0
        last = transport.json("mouflon/last_bird")[-1]
        assert last["status"] == "provisional"
        assert last["confirmation_progress"] == 50
        assert last["confirmation_steps"][2]["note"] == "Perch entend autre chose"

    def test_silent_check_rescues_a_plausible_bird_perch_agrees_with(self, tmp_path):
        local = weekly(["Turdus merula"])
        service, transport, spy, source = build(
            tmp_path, "Turdus merula_Eurasian Blackbird", 0.3, local=local
        )
        service.birdlog.history = lambda *_: (False, 200)
        assert service.handle_window(source, WINDOW_AUDIO) == 0
        assert len(spy.windows) == 1
        last = transport.json("mouflon/last_bird")[-1]
        assert last["status"] == "provisional"
        assert last["confirmation_progress"] == 67  # 2 of 3 checks
        assert transport.json("mouflon/silent_check")[-1]["rescued"] == 1
        # A low repeat is not enough; one more published detection confirms it.
        service.handle_window(source, WINDOW_AUDIO)
        assert transport.json("mouflon/last_bird")[-1]["status"] == "provisional"
        service.detector = FilteringDetector(
            lambda _w: [("Turdus merula_Eurasian Blackbird", 0.6)], 0.2
        )
        service.handle_window(source, WINDOW_AUDIO)
        assert transport.json("mouflon/last_bird")[-1]["status"] == "confirmed"

    def test_silent_check_drops_quietly_when_perch_is_below_agreement(self, tmp_path):
        local = weekly(["Turdus merula"])
        service, transport, spy, source = build(
            tmp_path, "Turdus merula_Eurasian Blackbird", 0.3, local=local
        )
        spy.score = 0.5
        assert service.handle_window(source, WINDOW_AUDIO) == 0
        assert transport.json("mouflon/last_bird") == []
        assert transport.json("mouflon/silent_check")[-1] == {
            "rescued": 0,
            "rejected": 1,
            "skipped": 0,
        }

    def test_silent_check_never_asks_perch_for_a_locally_rare_bird(self, tmp_path):
        service, transport, spy, source = build(
            tmp_path, "Upupa epops_Eurasian Hoopoe", 0.3, local=weekly([])
        )
        assert service.handle_window(source, WINDOW_AUDIO) == 0
        assert spy.windows == []
        assert transport.json("mouflon/last_bird") == []
        assert transport.json("mouflon/silent_check")[-1]["rejected"] == 1

    def test_silent_check_counter_resets_daily(self, tmp_path):
        service, transport, _, source = build(
            tmp_path, "Upupa epops_Eurasian Hoopoe", 0.3, local=weekly([])
        )
        service.handle_window(source, WINDOW_AUDIO)
        service.daily_maintenance()
        assert transport.json("mouflon/silent_check")[-1]["rejected"] == 0

    def test_second_opinion_turned_off(self, tmp_path):
        service, transport, spy, source = build(
            tmp_path,
            "Upupa epops_Eurasian Hoopoe",
            0.9,
            raw={"second_opinion": False},
        )
        service.handle_window(source, WINDOW_AUDIO)
        assert spy.windows == []
        step = transport.json("mouflon/last_bird")[-1]["confirmation_steps"][2]
        assert (step["state"], step["note"]) == (
            "skipped",
            "désactivé dans les réglages",
        )

    def test_no_window_survives_the_analysis(self, tmp_path):
        local = weekly(["Turdus merula"])
        service, transport, _, source = build(
            tmp_path, "Upupa epops_Eurasian Hoopoe", 0.9, "disagree", local
        )
        marker = WINDOW_AUDIO.size + 7  # a size no other array in the test has
        service.handle_window(source, np.ones(marker, dtype=np.float32))
        gc.collect()
        kept = [
            o
            for o in gc.get_objects()
            if isinstance(o, np.ndarray) and o.size == marker
        ]
        assert kept == []
        text = json.dumps([p for _, p, _ in transport.messages if p])
        assert "audio" not in text.lower()
        files = {p.name for p in (tmp_path / "data").rglob("*") if p.is_file()}
        assert files <= {"birdlog.sqlite", "birdlog.sqlite-journal"}


# --- local statistics ----------------------------------------------------------------


class TestLocalObservations:
    def test_levels_use_the_week_and_its_neighbours(self):
        counts = [0] * WEEKS
        counts[17] = 40  # week 18 only
        data = LocalObservations(
            {
                "calendar": "birdnet-48",
                "totals": [10_000] * WEEKS,
                "species": {"Upupa epops": counts},
            }
        )
        assert data.level("Upupa epops", 18) == "observed"
        assert data.level("Upupa epops", 19) == "observed"  # neighbour week
        assert data.level("Upupa epops", 30) == "rare"
        assert data.level("Avis inexistens", 18) == "rare"

    def test_aliases(self):
        data = weekly(["Coloeus monedula"])
        assert data.level("Corvus monedula", 1) == "observed"

    def test_bad_files_are_unavailable_not_fatal(self, tmp_path):
        assert LocalObservations.load(tmp_path) is None
        (tmp_path / "belgium-weekly.json").write_text('{"calendar": "other"}')
        assert LocalObservations.load(tmp_path) is None

    def test_test_mode_skips_the_local_check(self, tmp_path):
        service, *_ = build(
            tmp_path, "Upupa epops_Eurasian Hoopoe", 0.9, raw={"test_mode": True}
        )
        assert service.local_level("Upupa epops", START) == "skipped:test"


# --- bundled data and pins ----------------------------------------------------------


def test_perch_is_pinned_by_revision_and_fingerprint():
    assert re.fullmatch(r"[0-9a-f]{40}", models.PERCH_REVISION)
    assert models.PERCH_REVISION in models.PERCH_BASE_URL
    lock = json.loads((ROOT / "app/models.lock.json").read_text())["files"]
    for name in models.PERCH_FILES:
        assert re.fullmatch(r"[0-9a-f]{64}", lock[f"{so.PERCH_DIR}/{name}"])


@pytest.mark.skipif(
    not (CROSSCHECK / "belgium-weekly.json").exists(), reason="no bundled statistics"
)
class TestBundledData:
    def test_weekly_statistics_are_country_level_and_complete(self):
        data = json.loads((CROSSCHECK / "belgium-weekly.json").read_text())
        assert data["calendar"] == "birdnet-48"
        assert len(data["years"]) == 10
        text = json.dumps(data).lower()
        assert "latitude" not in text
        assert "longitude" not in text
        observations = LocalObservations(data)
        for common in ("Turdus merula", "Erithacus rubecula", "Parus major"):
            assert all(observations.level(common, w) == "observed" for w in (1, 18, 40))
        assert len(observations.species) > 300

    def test_manifest_cites_every_dataset_and_keeps_open_records_only(self):
        manifest = json.loads((CROSSCHECK / "manifest.json").read_text())
        assert manifest["datasets"]
        # Records are selected by their own licence: CC0 1.0 or CC BY 4.0 only.
        assert manifest["filters"]["license"] == ["CC0_1_0", "CC_BY_4_0"]
        for dataset in manifest["datasets"]:
            assert dataset["doi"]
            assert dataset["citation"]
        assert manifest["gbif_citation"].startswith("GBIF.org (")

    def test_library_species_map_to_perch(self):
        aliases = json.loads((CROSSCHECK / "perch-aliases.json").read_text())
        catalogue = json.loads((ROOT / "app/library/catalogue.json").read_text())
        missing = aliases["not_in_perch"]
        assert len(missing) <= 0.05 * len(catalogue["species"])


# --- the real Perch, when its files are present (CI downloads them) ----------------


@pytest.fixture(scope="module")
def real_perch():
    folder = models.app_data() / so.PERCH_DIR
    if not (folder / so.MODEL_FILE).exists():
        if os.environ.get("GITHUB_ACTIONS"):
            pytest.fail("Perch must be downloaded in CI")
        pytest.skip("Perch model not available here")
    perch = so.SecondOpinion(folder, load=lambda: 0.0)
    perch.load_model()
    assert perch.ready, perch.status
    return perch


def test_real_perch_agrees_with_birdnet_on_the_test_recording(real_perch):
    from mouflon_population.sources import FileSource

    windows = list(
        FileSource("example", EXAMPLE, realtime=False).windows(threading.Event())
    )
    # Black-capped chickadee, first window of the bundled recording (MOUL-54 bench).
    result = real_perch.ask(windows[0], "Poecile atricapillus")
    assert result.verdict == "agree"
    # Quiet background noise (no bird): Perch must not hear a chickadee.
    noise = np.random.default_rng(1).standard_normal(windows[0].shape) * 3e-3
    quiet = real_perch.ask(noise.astype(np.float32), "Poecile atricapillus")
    assert quiet.verdict == "disagree", quiet
    muted = real_perch.ask(np.zeros_like(windows[0]), "Poecile atricapillus")
    assert muted.verdict == "skipped:silence"


def test_perch_download_retries_until_the_fingerprint_matches(tmp_path, monkeypatch):
    import hashlib

    good = {name: f"{name} content".encode() for name in models.PERCH_FILES}
    lock = tmp_path / "models.lock.json"
    lock.write_text(
        json.dumps(
            {
                "files": {
                    f"{so.PERCH_DIR}/{n}": hashlib.sha256(c).hexdigest()
                    for n, c in good.items()
                }
            }
        )
    )
    calls = []

    def fetch(url, partial):
        name = url.rsplit("/", 1)[1]
        calls.append(name)
        truncated = calls.count(name) == 1
        partial.write_bytes(good[name][:3] if truncated else good[name])

    monkeypatch.setattr(models, "_fetch", fetch)
    models.download_perch(tmp_path / "data", lock)
    for name, content in good.items():
        assert (tmp_path / "data" / so.PERCH_DIR / name).read_bytes() == content
    assert len(calls) == 2 * len(good)


def test_perch_download_gives_up_on_a_wrong_file(tmp_path, monkeypatch):
    lock = tmp_path / "models.lock.json"
    lock.write_text(
        json.dumps({"files": {f"{so.PERCH_DIR}/{models.MODEL_FILE}": "0" * 64}})
    )
    monkeypatch.setattr(models, "_fetch", lambda _u, p: p.write_bytes(b"tampered"))
    with pytest.raises(RuntimeError, match="pinned fingerprint"):
        models.download_perch(tmp_path / "data", lock)
    assert not (tmp_path / "data" / so.PERCH_DIR / models.MODEL_FILE).exists()
