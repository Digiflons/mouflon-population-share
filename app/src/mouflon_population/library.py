"""The bundled bird library (epic MOUL-42): drawings, reference songs, IUCN status.

Everything is read from files inside the App image (``app/library/``), built by the
illustration pipeline in GitHub Actions. The Pi never fetches anything from the
internet.

Reference songs are third-party recordings of each species (xeno-canto). They are
**not** sound from the garden cameras, which is never kept.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

LIBRARY_DIR = Path(os.environ.get("MOUFLON_LIBRARY", "/opt/mouflon/library"))
MEDIA_DIR = Path(os.environ.get("MOUFLON_MEDIA_DIR", "/media/mouflon_population"))
MEDIA_SOURCE_PREFIX = "media-source://media_source/local/mouflon_population"
THREATENED = {
    "NT": "Near threatened",
    "VU": "Vulnerable",
    "EN": "Endangered",
    "CR": "Critically endangered",
}


def slug(scientific: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", scientific.lower()).strip("_")


@dataclass(frozen=True)
class Entry:
    scientific: str
    common_name: str
    image: str | None
    credit: str | None
    iucn: str | None
    song: str | None
    song_credit: str | None


class Library:
    def __init__(self, root: Path = LIBRARY_DIR):
        self.root = root
        path = root / "catalogue.json"
        self._entries: dict[str, dict] = {}
        if path.exists():
            self._entries = json.loads(path.read_text(encoding="utf-8"))["species"]
        log.info(
            "Bird library: %d species, %d drawings, %d songs",
            len(self._entries),
            sum(1 for e in self._entries.values() if e.get("image")),
            sum(1 for e in self._entries.values() if e.get("song")),
        )

    def get(self, scientific: str) -> Entry | None:
        raw = self._entries.get(scientific)
        if raw is None:
            return None
        return Entry(
            scientific=scientific,
            common_name=raw.get("common_name", scientific),
            image=raw.get("image"),
            credit=raw.get("credit"),
            iucn=raw.get("iucn"),
            song=raw.get("song"),
            song_credit=raw.get("song_credit"),
        )

    def image_bytes(self, scientific: str) -> bytes | None:
        entry = self.get(scientific)
        if entry is None or not entry.image:
            return None
        path = self.root / "images" / entry.image
        return path.read_bytes() if path.is_file() else None

    def song_media_id(self, scientific: str) -> str | None:
        entry = self.get(scientific)
        if entry is None or not entry.song:
            return None
        return f"{MEDIA_SOURCE_PREFIX}/songs/{entry.song}"

    def install_songs(self, media_dir: Path = MEDIA_DIR) -> int:
        """Copy the bundled reference songs into Home Assistant's media folder.

        Only files from the library are written, only under ``media_dir``; nothing
        else in the media folder is read or touched.
        """
        source = self.root / "songs"
        if not source.is_dir():
            return 0
        target = media_dir / "songs"
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            log.warning("Reference songs not installed (%s)", error)
            return 0
        copied = 0
        for song in sorted(source.glob("*.mp3")):
            destination = target / song.name
            if (
                not destination.exists()
                or destination.stat().st_size != song.stat().st_size
            ):
                shutil.copyfile(song, destination)
                copied += 1
        log.info("Reference songs ready in the media folder (%d updated)", copied)
        return copied
