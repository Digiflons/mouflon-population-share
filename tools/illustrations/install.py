"""Install a reviewed pipeline run into the repository (MOUL-43/44/45/47/48).

    python tools/illustrations/install.py <full library build> [--extra <demo pack>]

- the full library replaces whatever was installed before (0.6.0: it replaces the
  demo starter pack);
- ``--extra``: a reviewed build whose drawings fill only the species the main
  build has no drawing for (0.6.0: the hoopoe of demo mode, not on the regional
  species list); main-build drawings always win;

- app/library/catalogue.json: per species common name, drawing, credit, IUCN
  category, reference song and its credit (what the App bundles);
- app/library/images/ and app/library/songs/: the Home Assistant renditions;
- docs/illustrations/: manifests, coverage report and contact sheet (review).

Images flagged "needs crop" are not bundled until crops.json gives them a box.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LICENCE_NAMES = {
    "by": "CC BY",
    "by-sa": "CC BY-SA",
    "by-nc": "CC BY-NC",
    "by-nc-sa": "CC BY-NC-SA",
}


def licence_label(url: str) -> str:
    match = re.search(r"/licenses/([a-z-]+)/([\d.]+)", url or "")
    if not match:
        return url or "unknown licence"
    return f"{LICENCE_NAMES.get(match.group(1), match.group(1))} {match.group(2)}"


def image_credit(item: dict) -> str:
    book = item["book"].split(" (")[0]
    plate = item["plate"]
    if plate == "plate not identified":
        plate = Path(item["commons_title"].removeprefix("File:")).stem
    return f"{book}, {plate}. Public domain, via Wikimedia Commons."


def song_credit(song: dict) -> str:
    return (
        f"{song['recordist']}, xeno-canto XC{song['xeno_canto_id']}, "
        f"{licence_label(song['licence'])}"
    )


def _read(folder: Path, name: str):
    return json.loads((folder / name).read_text(encoding="utf-8"))


def add_extra(extra: Path, catalogue: dict, images_dir: Path) -> int:
    """Drawings from a second reviewed build, only where the main one has none."""
    taxa, species = _read(extra, "taxa.json"), _read(extra, "species.json")
    added = 0
    for item in _read(extra, "manifest.json"):
        name = item["species"]
        if item["needs_crop"] or catalogue.get(name, {}).get("image"):
            continue
        entry = catalogue.setdefault(
            name,
            {"common_name": species[name]["common_name"], "iucn": taxa[name]["iucn"]},
        )
        shutil.copyfile(extra / "ha" / item["image"], images_dir / item["image"])
        entry.update(image=item["image"], credit=image_credit(item))
        added += 1
    return added


def main(artifact: Path, extra: Path | None = None) -> int:
    taxa = _read(artifact, "taxa.json")
    species = _read(artifact, "species.json")
    images = _read(artifact, "manifest.json")
    songs_path = artifact / "songs-manifest.json"
    songs = json.loads(songs_path.read_text()) if songs_path.exists() else []

    library = ROOT / "app" / "library"
    for sub in ("images", "songs"):
        shutil.rmtree(library / sub, ignore_errors=True)
        (library / sub).mkdir(parents=True)
    catalogue = {
        name: {"common_name": species[name]["common_name"], "iucn": taxa[name]["iucn"]}
        for name in sorted(species)
    }
    for item in images:
        if item["needs_crop"]:
            continue
        shutil.copyfile(
            artifact / "ha" / item["image"], library / "images" / item["image"]
        )
        catalogue[item["species"]].update(
            image=item["image"], credit=image_credit(item)
        )
    for song in songs:
        shutil.copyfile(
            artifact / "songs" / song["file"], library / "songs" / song["file"]
        )
        catalogue[song["species"]].update(
            song=song["file"], song_credit=song_credit(song)
        )
    from_extra = add_extra(extra, catalogue, library / "images") if extra else 0
    (library / "catalogue.json").write_text(
        json.dumps({"species": catalogue}, indent=1, ensure_ascii=False, sort_keys=True)
        + "\n"
    )

    docs = ROOT / "docs" / "illustrations"
    docs.mkdir(parents=True, exist_ok=True)
    for name in (
        "manifest.json",
        "songs-manifest.json",
        "coverage.md",
        "contact-sheet.html",
    ):
        if (artifact / name).exists():
            shutil.copyfile(artifact / name, docs / name)
    with_image = sum(1 for c in catalogue.values() if c.get("image"))
    with_song = sum(1 for c in catalogue.values() if c.get("song"))
    skipped = sum(1 for item in images if item["needs_crop"])
    print(
        f"{len(catalogue)} species, {with_image} drawings "
        f"({from_extra} from the extra build), {with_song} songs installed; "
        f"{skipped} drawings skipped (need a crop box)"
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("build", type=Path)
    parser.add_argument("--extra", type=Path)
    args = parser.parse_args()
    sys.exit(main(args.build, args.extra))
