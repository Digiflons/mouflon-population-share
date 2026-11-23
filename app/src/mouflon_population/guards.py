"""Guards that decide whether a source may listen right now (MOUL-37).

- Battery guard: battery-powered cameras stop being woken below the stop threshold
  and resume only above the resume level; a too fast drop also stops them. If the
  level cannot be read, or is stale, the guard fails safe and does not listen.
- When to listen (MOUL-39): from sunrise to sunset by default (Home Assistant's
  sun entity), or during configured times of day, or always. If the sun's position
  is unknown, the App does not listen.
- Weather guard (optional): pause in strong wind or rain; unknown weather does not
  block.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mouflon_population.config import Window

# Battery cameras report rarely while asleep; older readings are treated as unknown.
STALE_AFTER = timedelta(hours=6)
DROP_PERIOD = timedelta(hours=24)


@dataclass(frozen=True)
class Reading:
    value: float | None
    updated_at: datetime | None


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str


class BatteryGuard:
    def __init__(self, stop_below: float, resume_above: float, max_drop_per_day: float):
        self.stop_below = stop_below
        self.resume_above = resume_above
        self.max_drop_per_day = max_drop_per_day
        self._stopped_low = False
        self._history: deque[tuple[datetime, float]] = deque()

    def check(self, reading: Reading, now: datetime) -> Verdict:
        if reading.value is None or reading.updated_at is None:
            return Verdict(False, "paused: battery unknown")
        if now - reading.updated_at > STALE_AFTER:
            return Verdict(False, "paused: battery reading too old")
        level = reading.value
        self._remember(now, level)
        if self._stopped_low:
            if level >= self.resume_above:
                self._stopped_low = False
            else:
                return Verdict(False, f"paused: battery low ({level:.0f} %)")
        if level < self.stop_below:
            self._stopped_low = True
            return Verdict(False, f"paused: battery low ({level:.0f} %)")
        drop = self.drop_last_day()
        if drop > self.max_drop_per_day:
            return Verdict(False, f"paused: battery dropping fast ({drop:.0f} %/day)")
        return Verdict(True, "ok")

    def _remember(self, now: datetime, level: float) -> None:
        self._history.append((now, level))
        while self._history and now - self._history[0][0] > DROP_PERIOD:
            self._history.popleft()

    def drop_last_day(self) -> float:
        if len(self._history) < 2:
            return 0.0
        peak = max(level for _, level in self._history)
        return max(0.0, peak - self._history[-1][1])


def daylight_verdict(sun_state: str | None) -> Verdict:
    if sun_state == "above_horizon":
        return Verdict(True, "ok")
    if sun_state == "below_horizon":
        return Verdict(False, "outside daylight")
    return Verdict(False, "paused: sun position unknown")


def window_verdict(windows: tuple[Window, ...], now: datetime) -> Verdict:
    if not windows:
        return Verdict(True, "ok")
    moment = now.time()
    if any(w.contains(moment) for w in windows):
        return Verdict(True, "ok")
    return Verdict(False, "outside listening window")


def weather_verdict(
    wind_kmh: float | None, rain: float | None, max_wind_kmh: float
) -> Verdict:
    if wind_kmh is not None and wind_kmh > max_wind_kmh:
        return Verdict(False, f"paused: wind ({wind_kmh:.0f} km/h)")
    if rain is not None and rain > 0:
        return Verdict(False, "paused: rain")
    return Verdict(True, "ok")
