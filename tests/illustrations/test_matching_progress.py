"""Offline tests for the library pipeline's name matching and progress lines."""

import importlib
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "illustrations"


@pytest.fixture(scope="module")
def tools():
    sys.path.insert(0, str(TOOLS))
    try:
        yield (
            importlib.import_module("matching"),
            importlib.import_module("progress"),
        )
    finally:
        sys.path.remove(str(TOOLS))


TAXA = {
    "Ardea cinerea": {
        "names": ["Ardea cinerea"],
        "items": ["Q1"],
        "vernacular": ["Graureiher", "Fischreiher", "Grey Heron"],
    },
    "Cinclus cinclus": {
        "names": ["Cinclus cinclus", "Cinclus aquaticus"],
        "items": ["Q2"],
        "vernacular": ["Wasseramsel"],
    },
    "Corvus corone": {
        "names": ["Corvus corone"],
        "items": ["Q3"],
        "vernacular": ["Rabenkrähe"],
    },
}


def test_synonym_in_category_matches(tools):
    matching, _ = tools
    index = matching.Index(TAXA)
    meta = {
        "title": "File:Naumann 1905 Tafel 3.jpg",
        "categories": ["Category:Cinclus aquaticus (illustrations)"],
    }
    assert index.matches(meta) == {"Cinclus cinclus": "illustrations-category"}


def test_depicts_and_text_and_old_german_names(tools):
    matching, _ = tools
    index = matching.Index(TAXA)
    assert index.matches({"title": "File:x.jpg"}, ["Q3"]) == {
        "Corvus corone": "depicts"
    }
    meta = {"title": "File:Naumann-Fischreiher.jpg", "description": "<p>Tafel 12</p>"}
    assert index.matches(meta) == {"Ardea cinerea": "vernacular-in-text"}
    meta = {"title": "File:plate.jpg", "description": "1. Corvus&nbsp;corone, 2. x"}
    assert index.matches(meta) == {"Corvus corone": "scientific-in-text"}


def test_strongest_match_wins_and_words_are_whole(tools):
    matching, _ = tools
    index = matching.Index(TAXA)
    meta = {
        "title": "File:Ardea cinerea.jpg",
        "categories": ["Category:Ardea cinerea in art"],
    }
    assert index.matches(meta) == {"Ardea cinerea": "category"}
    assert index.matches({"title": "File:Graureihers-Nest.jpg"}) == {}


def test_normalise_handles_accents_and_eszett(tools):
    matching, _ = tools
    assert matching.normalise("Großer <b>Rabenkrähe</b>") == "grosser rabenkrahe"


def test_progress_lines_and_summary(tools, tmp_path, monkeypatch, capsys):
    _, progress = tools
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    ticks = iter([0, 120, 600, 600, 600])
    run = progress.Progress(3, every=2, clock=lambda: next(ticks))
    assert run.species("Parus major", "Naumann", True) == (
        "[1/3] Parus major — plate: found (Naumann) | song: found"
    )
    run.species("Pica pica", None, False)
    out = capsys.readouterr().out
    assert "plates 1/2, failed 0, songs 1/2, elapsed 2 min, ~1 min remaining" in out
    run.species("Turdus merula", "Dresser", True)
    run.summary(["- extra"])
    text = summary.read_text(encoding="utf-8")
    assert "With a plate: 2" in text
    assert "- extra" in text
    assert "http" not in out + text


def test_contact_goes_only_to_wikimedia_and_is_never_printed(tools, monkeypatch):
    monkeypatch.setenv("WIKIMEDIA_CONTACT", "someone@example.org")
    sys.path.insert(0, str(TOOLS))
    try:
        sys.modules.pop("commons", None)
        commons = importlib.import_module("commons")
        assert "someone@example.org" in commons.agent_for(
            "https://commons.wikimedia.org/w/api.php"
        )
        assert "example.org" not in commons.agent_for("https://api.gbif.org/v1/x")
        assert "example.org" not in commons.public_user_agent()
        source = (TOOLS / "pipeline.py").read_text(encoding="utf-8")
        assert "USER_AGENT" not in source
    finally:
        sys.modules.pop("commons", None)
        sys.path.remove(str(TOOLS))
