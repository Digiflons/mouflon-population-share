"""Permanent table of real garden detections, for seasonal analytics (MOUL-51).

- Separate SQLite file in the App's data folder (so it is part of Home Assistant's
  App backups), **never purged**: the bird log's retention setting does not touch it.
- Only real detections with their final status: "confirmed" (counted) or
  "withdrawn" (a provisional bird that was not confirmed; never counted). Demo and
  test detections never enter it.
- Text only: never audio.
- Schema ready for later views (species per month or season, first/last date per
  year, year-over-year): local date, year, month and BirdNET week are stored.
- CSV export on demand, written to the App's folder in Home Assistant's media folder.
"""

from __future__ import annotations

import csv
import sqlite3
import threading
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

SCHEMA_VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT NOT NULL,
    local_date TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    week INTEGER NOT NULL,
    scientific_name TEXT NOT NULL,
    common_name TEXT NOT NULL,
    confidence REAL NOT NULL,
    source TEXT NOT NULL,
    garden_rarity TEXT,
    regional_rarity TEXT,
    iucn TEXT,
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'withdrawn')),
    app_version TEXT NOT NULL,
    model_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS analytics_species_time
    ON detections (scientific_name, detected_at);
CREATE INDEX IF NOT EXISTS analytics_period ON detections (year, month, week);
"""
COLUMNS = (
    "detected_at",
    "local_date",
    "year",
    "month",
    "week",
    "scientific_name",
    "common_name",
    "confidence",
    "source",
    "garden_rarity",
    "regional_rarity",
    "iucn",
    "status",
    "app_version",
    "model_version",
)


@dataclass(frozen=True)
class AnalyticsRow:
    detected_at: datetime
    scientific_name: str
    common_name: str
    confidence: float
    source: str
    garden_rarity: str | None
    regional_rarity: str | None
    iucn: str | None
    status: str
    app_version: str
    model_version: str


def birdnet_week(day: datetime) -> int:
    return (day.month - 1) * 4 + min(4, (day.day - 1) // 7 + 1)


class AnalyticsStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._db.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._db.commit()
        self._lock = threading.Lock()

    def add(self, row: AnalyticsRow) -> None:
        if row.status not in ("confirmed", "withdrawn"):
            raise ValueError(f"unexpected status {row.status!r}")
        when = row.detected_at
        values = {
            **asdict(row),
            "detected_at": when.isoformat(timespec="seconds"),
            "local_date": when.date().isoformat(),
            "year": when.year,
            "month": when.month,
            "week": birdnet_week(when),
        }
        with self._lock, self._db:
            self._db.execute(
                f"INSERT INTO detections ({', '.join(COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in COLUMNS)})",
                tuple(values[c] for c in COLUMNS),
            )

    def count(self, status: str | None = None) -> int:
        with self._lock:
            if status is None:
                return self._db.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
            return self._db.execute(
                "SELECT COUNT(*) FROM detections WHERE status = ?", (status,)
            ).fetchone()[0]

    def sources(self) -> set[str]:
        with self._lock:
            rows = self._db.execute("SELECT DISTINCT source FROM detections").fetchall()
        return {r[0] for r in rows}

    def export_csv(self, folder: Path, now: datetime) -> tuple[Path, int]:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"bird-analytics-{now:%Y%m%d-%H%M%S}.csv"
        with self._lock:
            rows = self._db.execute(
                f"SELECT {', '.join(COLUMNS)} FROM detections ORDER BY detected_at, id"
            ).fetchall()
        with target.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS)
            writer.writerows(rows)
        return target, len(rows)

    def close(self) -> None:
        self._db.close()
