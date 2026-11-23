"""What the dashboard's Gallery shows (MOUL-45, MOUL-47, MOUL-48).

- the last bird's drawing, as a Home Assistant image entity;
- today's species list (most recent first, at most 30) on the "Species today"
  sensor, the first six with their drawing in six image entities;
- for each bird: credit line, reference song (a media-source id) and rarity.

Images go to Home Assistant over MQTT as image entities, so Home Assistant serves
them itself (also through Home Assistant Cloud), without any internet fetch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mouflon_population import i18n
from mouflon_population.mqtt_publisher import (
    LAST_BIRD_IMAGE,
    TODAY_SLOTS,
    image_entity_id,
    slot_object_id,
)

if TYPE_CHECKING:
    from datetime import datetime

    from mouflon_population.library import Library
    from mouflon_population.mqtt_publisher import Publisher

MAX_SPECIES = 30
_UNSET = "\0unset"


class Gallery:
    def __init__(
        self,
        publisher: Publisher,
        library: Library | None,
        screen_size: tuple[int, int] | None = (480, 800),
        screen_refresh_s: float = 600.0,
        screen_view: str = "collage",
    ):
        self.publisher = publisher
        self.library = library
        self.screen_size = screen_size
        self.screen_refresh_s = screen_refresh_s
        self.screen_view = (
            screen_view if screen_view in ("collage", "alternate") else "collage"
        )
        self._screen_page = 0
        self._screen_last: dict | None = None
        self._screen_species: list[dict] = []
        self._screen_dirty = True
        self._screen_rendered_at: datetime | None = None
        self._slots: list[str | None] = [_UNSET] * TODAY_SLOTS
        self._renditions: dict[str, bytes] = {}
        self._last: str | None = _UNSET

    def extras(self, scientific: str) -> dict:
        entry = self.library.get(scientific) if self.library else None
        return {
            "credit": entry.credit if entry else None,
            "has_drawing": bool(entry and entry.image),
            "song": self.library.song_media_id(scientific) if self.library else None,
            "song_credit": entry.song_credit if entry else None,
            "iucn": entry.iucn if entry else None,
        }

    def enrich(self, detection: dict) -> dict:
        self._screen_last = detection
        self._screen_dirty = True
        return {
            **detection,
            **self.extras(detection["scientific_name"]),
            "image": image_entity_id(LAST_BIRD_IMAGE),
        }

    def _image(self, scientific: str | None) -> bytes | None:
        """The drawing on aged paper with an organic edge (0.5.3), or the French
        "drawing to come" card in the same style. Cached: plates never change."""
        if self.library is None:
            return None
        from mouflon_population import screen, vintage

        data = self.library.image_bytes(scientific) if scientific else None
        key = f"plate:{scientific}" if data else f"placeholder:{i18n.current()}"
        if key not in self._renditions:
            if data:
                self._renditions[key] = vintage.rendition(data, scientific)
            else:
                font = str(screen.FONTS / "IMFellEnglish-Italic.ttf")
                text = i18n.t("drawing_to_come")
                self._renditions[key] = vintage.placeholder(text, font)
        return self._renditions[key]

    def show_last(self, scientific: str | None) -> None:
        if scientific == self._last:
            return
        self._last = scientific
        data = self._image(scientific)
        if data:
            self.publisher.image(LAST_BIRD_IMAGE, data)

    def show_species(self, species: list[dict], rarity: dict[str, dict]) -> None:
        items = []
        for index, item in enumerate(species[:MAX_SPECIES]):
            extras = self.extras(item["scientific_name"])
            slot = index < TODAY_SLOTS and extras["has_drawing"]
            items.append(
                {
                    **item,
                    **extras,
                    "image": image_entity_id(slot_object_id(index)) if slot else None,
                    "rarity": rarity.get(item["scientific_name"]),
                }
            )
        for index in range(TODAY_SLOTS):
            scientific = (
                species[index]["scientific_name"] if index < len(species) else None
            )
            if scientific != self._slots[index]:
                self._slots[index] = scientific
                data = self._image(scientific)
                if data:
                    self.publisher.image(slot_object_id(index), data)
        self.publisher.species_today(items)
        self._screen_species = items
        self._screen_dirty = True

    def render_screen_if_due(self, now: datetime) -> bool:
        """Slow refresh for the e-ink demo screen (MOUL-56): no animation."""
        if self.screen_size is None or not self._screen_dirty:
            return False
        if (
            self._screen_rendered_at is not None
            and (now - self._screen_rendered_at).total_seconds() < self.screen_refresh_s
        ):
            return False
        from mouflon_population import screen

        def image(scientific: str | None) -> bytes | None:
            return (
                self.library.image_bytes(scientific)
                if self.library and scientific
                else None
            )

        last = self._screen_last
        bird = (
            screen.bird_from_dict(
                {**last, **self.extras(last["scientific_name"])},
                image(last["scientific_name"]),
            )
            if last
            else None
        )
        birds = [
            screen.bird_from_dict(item, image(item["scientific_name"]))
            for item in self._screen_species[:10]
        ]
        options = screen.Options(i18n.current(), self.screen_view)
        pages = {
            "screen_last_bird": screen.render_last_bird(
                bird, self.screen_size, options, day=now
            ),
            "screen_today": screen.render_today(
                birds, now, self.screen_size, options=options
            ),
        }
        for object_id, page in pages.items():
            self.publisher.image(object_id, screen.png_bytes(page))
        if self.screen_view == "alternate":
            # One page per refresh, in turn; the frame keeps its slow rhythm.
            shown = list(pages.values())[self._screen_page % 2]
            self._screen_page += 1
        else:
            shown = screen.render_collage(bird, birds, now, self.screen_size, options)
        self.publisher.image("screen", screen.png_bytes(shown))
        self._screen_rendered_at = now
        self._screen_dirty = self.screen_view == "alternate"
        return True
