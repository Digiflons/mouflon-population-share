"""Offline tests for installing the full library over the demo pack (0.6.0, MOUL-44)."""

import importlib
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools" / "illustrations"


@pytest.fixture(scope="module")
def install():
    sys.path.insert(0, str(TOOLS))
    try:
        yield importlib.import_module("install")
    finally:
        sys.path.remove(str(TOOLS))


def _build(folder: Path, items: list[dict]) -> Path:
    (folder / "ha").mkdir(parents=True)
    names = {item["species"] for item in items}
    (folder / "species.json").write_text(
        json.dumps({n: {"common_name": n.upper()} for n in names})
    )
    (folder / "taxa.json").write_text(json.dumps({n: {"iucn": "LC"} for n in names}))
    for item in items:
        (folder / "ha" / item["image"]).write_bytes(b"from " + folder.name.encode())
    (folder / "manifest.json").write_text(json.dumps(items))
    return folder


def _item(species: str, needs_crop: bool = False) -> dict:
    return {
        "species": species,
        "image": species.lower().replace(" ", "_") + ".jpg",
        "needs_crop": needs_crop,
        "book": "Naumann, Naturgeschichte (1896)",
        "plate": "Tafel 1",
        "commons_title": "File:Plate.jpg",
    }


def test_extra_build_only_fills_species_without_a_drawing(install, tmp_path):
    extra = _build(
        tmp_path / "demo",
        [_item("Upupa epops"), _item("Pica pica"), _item("Turdus pilaris", True)],
    )
    images = tmp_path / "images"
    images.mkdir()
    (images / "pica_pica.jpg").write_bytes(b"from full")
    catalogue = {
        "Pica pica": {"common_name": "Magpie", "iucn": "LC", "image": "pica_pica.jpg"},
        "Turdus pilaris": {"common_name": "Fieldfare", "iucn": "LC"},
    }
    assert install.add_extra(extra, catalogue, images) == 1
    # The full build wins; the extra pack adds the species it lacks, with credit.
    assert (images / "pica_pica.jpg").read_bytes() == b"from full"
    assert catalogue["Upupa epops"]["image"] == "upupa_epops.jpg"
    assert "Public domain" in catalogue["Upupa epops"]["credit"]
    assert (images / "upupa_epops.jpg").read_bytes() == b"from demo"
    # A multi-species plate without a reviewed box is never installed.
    assert "image" not in catalogue["Turdus pilaris"]


def test_bundled_library_covers_every_demo_species_with_a_plate():
    root = TOOLS.parents[1]
    catalogue = json.loads((root / "app" / "library" / "catalogue.json").read_text())
    species = catalogue["species"]
    images = root / "app" / "library" / "images"
    for name, entry in species.items():
        if entry.get("image"):
            assert (images / entry["image"]).is_file(), name
            assert entry["credit"].endswith("Public domain, via Wikimedia Commons."), (
                name
            )
    # Every demo-pack drawing is still shown in demo mode (0.6.0).
    for name in ("Upupa epops", "Turdus merula", "Erithacus rubecula", "Pica pica"):
        assert species[name].get("image"), name
    assert sum(1 for e in species.values() if e.get("image")) >= 160
