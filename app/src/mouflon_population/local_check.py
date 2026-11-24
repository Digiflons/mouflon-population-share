"""Local observation check from bundled Belgian GBIF statistics (MOUL-55).

A GitHub workflow (``tools/crosscheck/crosscheck_data.py``) counts validated bird
observations in Belgium per species and per BirdNET week (four "weeks" per month)
over the last ten full years, at country level: no home coordinates are involved.
The result is bundled in the App (``crosscheck/belgium-weekly.json``); the Pi never
queries GBIF.

A species is "observed" at this time of year when, over the week and its two
neighbours, it has at least :data:`MIN_RECORDS` records and makes up at least
:data:`MIN_SHARE` of all bird records. Otherwise it is "rare" and needs the stronger
confirmation (heard twice, or Perch agreeing).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

CROSSCHECK_DIR = Path(os.environ.get("MOUFLON_CROSSCHECK", "/opt/mouflon/crosscheck"))
WEEKLY_FILE = "belgium-weekly.json"
WEEKS = 48
MIN_RECORDS = 30
MIN_SHARE = 1e-4


class LocalObservations:
    def __init__(self, data: dict):
        if data.get("calendar") != "birdnet-48":
            raise ValueError("unexpected calendar in the local statistics")
        self.totals: list[int] = data["totals"]
        self.species: dict[str, list[int]] = data["species"]
        self.aliases: dict[str, str] = data.get("aliases", {})
        self.years: list[int] = data.get("years", [])
        if len(self.totals) != WEEKS or any(
            len(c) != WEEKS for c in self.species.values()
        ):
            raise ValueError("the local statistics must have 48 weeks")

    @classmethod
    def load(cls, root: Path = CROSSCHECK_DIR) -> LocalObservations | None:
        path = root / WEEKLY_FILE
        try:
            observations = cls(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError) as error:
            log.warning("Local observation statistics unavailable: %s", error)
            return None
        log.info(
            "Local observation statistics: %d species, years %s",
            len(observations.species),
            "-".join(str(y) for y in observations.years[:1] + observations.years[-1:]),
        )
        return observations

    def _counts(self, scientific: str) -> list[int] | None:
        found = self.species.get(scientific)
        if found is None and scientific in self.aliases:
            found = self.species.get(self.aliases[scientific])
        return found

    @staticmethod
    def _around(values: list[int], week: int) -> int:
        i = week - 1
        return values[(i - 1) % WEEKS] + values[i] + values[(i + 1) % WEEKS]

    def share(self, scientific: str, week: int) -> tuple[int, float]:
        counts = self._counts(scientific)
        if counts is None:
            return 0, 0.0
        records = self._around(counts, week)
        total = self._around(self.totals, week)
        return records, (records / total if total else 0.0)

    def level(self, scientific: str, week: int) -> str:
        records, share = self.share(scientific, week)
        return "observed" if records >= MIN_RECORDS and share >= MIN_SHARE else "rare"
