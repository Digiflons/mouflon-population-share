"""The bird log (MOUL-28): the only data the App keeps.

Firm rule: each row holds species, confidence, source and time. No audio, no
recording, nothing else. Rows older than the retention period are deleted.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT NOT NULL,
    source TEXT NOT NULL,
    scientific_name TEXT NOT NULL,
    common_name TEXT NOT NULL,
    confidence REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS detections_time ON detections (detected_at);
"""
ALLOWED_COLUMNS = (
    "id",
    "detected_at",
    "source",
    "scientific_name",
    "common_name",
    "confidence",
)


@dataclass(frozen=True)
class LoggedDetection:
    detected_at: datetime
    source: str
    scientific_name: str
    common_name: str
    confidence: float

    def as_dict(self) -> dict:
        return {
            "detected_at": self.detected_at.isoformat(timespec="seconds"),
            "source": self.source,
            "scientific_name": self.scientific_name,
            "common_name": self.common_name,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class DayStats:
    species: int
    detections: int


class BirdLog:
    def __init__(self, path: Path, retention_days: int = 365):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self.retention = timedelta(days=retention_days)

    def add(self, entry: LoggedDetection) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO detections (detected_at, source, scientific_name,"
                " common_name, confidence) VALUES (?, ?, ?, ?, ?)",
                (
                    entry.detected_at.isoformat(timespec="seconds"),
                    entry.source,
                    entry.scientific_name,
                    entry.common_name,
                    entry.confidence,
                ),
            )

    def day_stats(self, day: datetime) -> DayStats:
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        with self._lock:
            species, detections = self._db.execute(
                "SELECT COUNT(DISTINCT scientific_name), COUNT(*) FROM detections"
                " WHERE detected_at >= ? AND detected_at < ?",
                (start.isoformat(), end.isoformat()),
            ).fetchone()
        return DayStats(species=species, detections=detections)

    def history(self, scientific: str, since: datetime) -> tuple[bool, int]:
        """(never logged before, distinct days logged since ``since``)."""
        with self._lock:
            ever, days = self._db.execute(
                "SELECT COUNT(*), COUNT(DISTINCT CASE WHEN detected_at >= ?"
                " THEN substr(detected_at, 1, 10) END)"
                " FROM detections WHERE scientific_name = ?",
                (since.isoformat(), scientific),
            ).fetchone()
        return ever == 0, days

    def day_species(self, day: datetime, limit: int = 30) -> list[dict]:
        """Today's species, most recently heard first."""
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        with self._lock:
            rows = self._db.execute(
                "SELECT scientific_name, MAX(common_name), COUNT(*), MAX(detected_at)"
                " FROM detections WHERE detected_at >= ? AND detected_at < ?"
                " GROUP BY scientific_name ORDER BY MAX(detected_at) DESC LIMIT ?",
                (start.isoformat(), end.isoformat(), limit),
            ).fetchall()
        return [
            {
                "scientific_name": r[0],
                "common_name": r[1],
                "count": r[2],
                "last_heard": r[3],
            }
            for r in rows
        ]

    def recent(self, limit: int = 50) -> list[LoggedDetection]:
        with self._lock:
            rows = self._db.execute(
                "SELECT detected_at, source, scientific_name, common_name, confidence"
                " FROM detections ORDER BY detected_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            LoggedDetection(datetime.fromisoformat(r[0]), r[1], r[2], r[3], r[4])
            for r in rows
        ]

    def purge(self, now: datetime) -> int:
        cutoff = (now - self.retention).isoformat()
        with self._lock, self._db:
            cursor = self._db.execute(
                "DELETE FROM detections WHERE detected_at < ?", (cutoff,)
            )
        return cursor.rowcount

    def columns(self) -> tuple[str, ...]:
        with self._lock:
            rows = self._db.execute("PRAGMA table_info(detections)").fetchall()
        return tuple(r[1] for r in rows)

    def close(self) -> None:
        self._db.close()
