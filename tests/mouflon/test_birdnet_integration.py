"""Real BirdNET 2.4 (LiteRT) on the bundled example recording.

Needs the models: downloaded in CI; skipped locally when they cannot be fetched.
"""

import os
from pathlib import Path

import pytest
from mouflon_population.detector import (
    BirdnetPredictor,
    FilteringDetector,
    species_for_location,
)
from mouflon_population.sources import FileSource

EXAMPLE = Path(__file__).resolve().parents[2] / "app/example/soundscape-60s.flac"


@pytest.fixture(scope="module")
def predictor():
    try:
        predictor = BirdnetPredictor()
    except Exception as error:
        if os.environ.get("GITHUB_ACTIONS"):
            raise
        pytest.skip(f"BirdNET model not available here: {error}")
    yield predictor
    predictor.close()


def test_finds_birds_in_the_example_recording(predictor):
    import threading

    detector = FilteringDetector(predictor, min_confidence=0.5)
    found = set()
    for window in FileSource("example", EXAMPLE, realtime=False).windows(
        threading.Event()
    ):
        found |= {d.scientific for d in detector.detect(window)}
    assert len(found) >= 2


def test_species_list_for_a_belgian_garden(predictor):
    species = species_for_location(50.85, 4.35, week=18)
    assert "Turdus merula" in species
    assert len(species) > 50
