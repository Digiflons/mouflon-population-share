"""Offline tests for the crop boxes of the library pipeline (0.5.3, MOUL-42)."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "illustrations"


@pytest.fixture(scope="module")
def pipeline():
    sys.path.insert(0, str(TOOLS))
    try:
        yield importlib.import_module("pipeline")
    finally:
        sys.path.remove(str(TOOLS))


def test_every_demo_crop_is_reviewed_and_generous():
    crops = json.loads((TOOLS / "crops.json").read_text(encoding="utf-8"))
    # 18 demo-pack plates (0.5.3) + 33 multi-species plates of the full library (0.6.0).
    assert len(crops) == 51
    for species, entry in crops.items():
        assert entry["commons_title"].startswith("File:"), species
        assert entry["note"], species
        box = entry["box"]
        if box == "whole":
            continue
        x0, y0, x1, y1 = box
        assert 0 <= x0 < x1 <= 1, species
        assert 0 <= y0 < y1 <= 1, species
        # Loose boxes only: at least a third of the plate in each direction.
        assert x1 - x0 >= 0.33, species
        assert y1 - y0 >= 0.3, species


def test_whole_plate_and_plate_fraction_boxes(pipeline):
    image = Image.new("RGB", (1000, 1500), "white")
    assert pipeline.chosen_box(image, {"box": "whole"})[0] == (0, 0, 1000, 1500)
    box, source = pipeline.chosen_box(image, {"box": [0.1, 0.2, 0.5, 0.6]})
    assert box == (100, 300, 500, 900)
    assert source == "crops.json"


def test_automatic_box_leaves_wide_margins(pipeline):
    image = Image.new("RGB", (1000, 1000), (240, 236, 220))
    image.paste((30, 30, 30), (400, 400, 600, 600))
    x0, y0, x1, y1 = pipeline.auto_box(image)
    assert x0 <= 350
    assert y0 <= 350
    assert x1 >= 650
    assert y1 >= 650


def test_automatic_box_takes_the_whole_plate_when_the_drawing_fills_it(pipeline):
    image = Image.new("RGB", (800, 1000), (240, 236, 220))
    image.paste((60, 120, 60), (60, 60, 740, 940))
    assert pipeline.auto_box(image) == (0, 0, 800, 1000)


def test_captions_are_blanked_with_the_plate_paper(pipeline):
    image = Image.new("RGB", (100, 100), (230, 225, 210))
    image.paste((0, 0, 0), (10, 85, 90, 95))
    pipeline.erase(image, [[0.0, 0.8, 1.0, 1.0]], (230, 225, 210))
    assert image.getpixel((50, 90)) == (230, 225, 210)
