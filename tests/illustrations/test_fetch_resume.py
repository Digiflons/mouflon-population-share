"""Offline tests for throttling, the deadline and resuming in the library pipeline
(MOUL-43): a busy Wikimedia must never turn a plate into "missing"."""

import email.message
import email.utils
import hashlib
import importlib
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "illustrations"
WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/illustrations.yml"


@pytest.fixture
def mods(monkeypatch):
    monkeypatch.setenv("WIKIMEDIA_CONTACT", "someone@example.org")
    sys.path.insert(0, str(TOOLS))
    for name in ("commons", "pipeline", "progress"):
        sys.modules.pop(name, None)
    try:
        commons = importlib.import_module("commons")
        pipeline = importlib.import_module("pipeline")
        clock = {"now": 1_000_000.0}
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            clock["now"] += seconds

        monkeypatch.setattr(commons, "_sleep", sleep)
        monkeypatch.setattr(commons, "_now", lambda: clock["now"])
        monkeypatch.setattr(pipeline.time, "sleep", lambda s: None)
        commons.set_deadline(None)
        commons._state["pause"] = commons.PAUSE_S
        yield commons, pipeline, clock, sleeps
    finally:
        sys.modules.pop("commons", None)
        sys.modules.pop("pipeline", None)
        sys.path.remove(str(TOOLS))


def http_error(code, retry_after=None):
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://x.invalid", code, "busy", headers, None)


def answers(*items):
    seen = []

    def urlopen(request, timeout):
        seen.append(request)
        item = items[min(len(seen), len(items)) - 1]
        if isinstance(item, Exception):
            raise item
        return io.BytesIO(item)

    return urlopen, seen


def test_429_is_retried_honouring_retry_after(mods, monkeypatch):
    commons, _, _, sleeps = mods
    urlopen, seen = answers(http_error(429, "42"), TimeoutError(), b"plate")
    monkeypatch.setattr(commons, "_urlopen", urlopen)
    assert commons.get_bytes("https://upload.wikimedia.org/a.jpg") == b"plate"
    assert len(seen) == 3
    assert 42 <= sleeps[0] <= 42 * 1.25
    assert commons._state["pause"] > commons.PAUSE_S  # slowed down after the 429


def test_persistent_throttling_raises_fetch_failed_not_404(mods, monkeypatch):
    commons, _, _, _ = mods
    urlopen, seen = answers(http_error(503))
    monkeypatch.setattr(commons, "_urlopen", urlopen)
    with pytest.raises(commons.FetchFailed, match="HTTP 503 after 6 attempts"):
        commons.get_bytes("https://upload.wikimedia.org/a.jpg")
    assert len(seen) == commons.ATTEMPTS


def test_definite_answer_is_not_retried(mods, monkeypatch):
    commons, _, _, _ = mods
    urlopen, seen = answers(http_error(404))
    monkeypatch.setattr(commons, "_urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError):
        commons.get_bytes("https://upload.wikimedia.org/a.jpg")
    assert len(seen) == 1


def test_very_long_retry_after_gives_up_politely(mods, monkeypatch):
    commons, _, _, sleeps = mods
    urlopen, seen = answers(http_error(429, "3600"))
    monkeypatch.setattr(commons, "_urlopen", urlopen)
    with pytest.raises(commons.FetchFailed):
        commons.get_bytes("https://upload.wikimedia.org/a.jpg")
    assert len(seen) == 1
    assert not sleeps


def test_retry_after_http_date(mods):
    commons, _, clock, _ = mods
    later = email.utils.formatdate(clock["now"] + 90, usegmt=True)
    assert commons.retry_after(later) == pytest.approx(90, abs=1)
    assert commons.retry_after("120") == 120
    assert commons.retry_after("soon") is None


def test_no_wait_runs_past_the_deadline(mods, monkeypatch):
    commons, _, clock, _ = mods
    urlopen, _ = answers(http_error(429, "60"))
    monkeypatch.setattr(commons, "_urlopen", urlopen)
    commons.set_deadline(clock["now"] + 30)
    with pytest.raises(commons.OutOfTime):
        commons.get_bytes("https://upload.wikimedia.org/a.jpg")


def entry(title, sha1="s1"):
    return {
        "common_name": title,
        "chosen": {
            "title": f"File:{title}.jpg",
            "book": "Naumann, Naturgeschichte",
            "plate": "Tafel 1",
            "descriptionurl": "https://commons.wikimedia.org/wiki/File:x",
            "url": "https://upload.wikimedia.org/x.jpg",
            "sha1": sha1,
            "license": "Public domain",
            "species_shown": [title],
        },
        "needs_crop": False,
        "needs_review": False,
        "match": "category",
    }


def run_download(pipeline, work, catalogue, fetch):
    (work / "catalogue.json").write_text(json.dumps(catalogue))
    (work / "catalogue-meta.json").write_text(
        json.dumps({"n_files": 3, "dresser": [], "match_kinds": {}})
    )
    pipeline.thumbnail_url = lambda title: title
    pipeline.get_bytes = fetch
    pipeline.step_download(work)
    return json.loads((work / "download-status.json").read_text())


def test_failed_downloads_are_reported_apart_from_missing(mods, tmp_path, capsys):
    commons, pipeline, _, _ = mods
    catalogue = {
        "A a": entry("A a"),
        "B b": entry("B b"),
        "C c": {**entry("C c"), "chosen": None},
    }

    def fetch(title):
        if "B b" in title:
            raise commons.FetchFailed("HTTP 429 after 6 attempts")
        return b"jpeg"

    status = run_download(pipeline, tmp_path, catalogue, fetch)
    assert status["failed"] == {"B b": "FetchFailed: HTTP 429 after 6 attempts"}
    out = capsys.readouterr().out
    assert "B b — plate: failed, retry later" in out
    assert "C c — plate: missing" in out
    assert "someone@example.org" not in out
    coverage = (tmp_path / "coverage.md").read_text()
    assert "failed, retry later (throttled or unreachable): **1**" in coverage
    assert "Species without a plate on Commons (missing): **1**" in coverage
    assert "## Failed, retry later\n\n- B b" in coverage


def test_a_second_run_resumes_from_the_cache(mods, tmp_path):
    commons, pipeline, _, _ = mods
    catalogue = {"A a": entry("A a"), "B b": entry("B b")}
    calls = []

    def first(title):
        calls.append(title)
        if "B b" in title:
            raise commons.OutOfTime
        return b"jpeg-a"

    status = run_download(pipeline, tmp_path, catalogue, first)
    assert status["not_attempted"] == ["B b"]
    assert status["stopped_early"]
    manifest = json.loads((tmp_path / "manifest-originals.json").read_text())
    assert [m["species"] for m in manifest] == ["A a"]

    calls.clear()
    status = run_download(
        pipeline, tmp_path, catalogue, lambda t: calls.append(t) or b"b"
    )
    assert calls == ["File:B b.jpg"]  # A a came from the cache
    assert status["reused_from_cache"] == 1
    assert not status["not_attempted"]


def test_cache_entry_is_dropped_when_commons_file_changed(mods, tmp_path):
    _, pipeline, _, _ = mods
    folder = tmp_path / "originals"
    folder.mkdir()
    cache = pipeline.PlateCache(folder)
    (folder / "a.jpg").write_bytes(b"x")
    digest = hashlib.sha256(b"x").hexdigest()
    cache.put("File:a.jpg", "old", {"file": "a.jpg", "sha256": digest})
    assert cache.get("File:a.jpg", "old")
    assert cache.get("File:a.jpg", "new") is None
    (folder / "a.jpg").write_bytes(b"tampered")
    assert cache.get("File:a.jpg", "old") is None


def test_workflow_stops_15_minutes_before_its_limit_and_keeps_demo_pack():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "timeout-minutes: 330" in text
    assert "(330 - 15) * 60" in text
    assert "! -name demo-pack" in text
