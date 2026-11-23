"""Detection delay (MOUL-52): from the end of a 3-second window to Home Assistant.

Breakdown per detection:
- inference: BirdNET on the window (and later checks, if any);
- publish: handing the messages to the MQTT client;
- home_assistant: until Home Assistant reports the new last-bird state (read back
  through the Supervisor, when available);
- stream_lag: delay of the camera stream itself, not measurable from inside the
  App; estimated in the benchmark on the real hardware (MOUL-12).

The rolling median and 95th percentile cover the last 100 detections.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Delay:
    inference_s: float
    publish_s: float
    home_assistant_s: float | None = None

    @property
    def total_s(self) -> float:
        return self.inference_s + self.publish_s + (self.home_assistant_s or 0.0)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


class LatencyTracker:
    def __init__(self, size: int = 100):
        self._totals: deque[float] = deque(maxlen=size)
        self.last: Delay | None = None

    def add(self, delay: Delay) -> dict:
        self.last = delay
        self._totals.append(delay.total_s)
        return self.summary()

    def summary(self) -> dict:
        values = list(self._totals)
        last = self.last
        return {
            "last_s": round(last.total_s, 2) if last else None,
            "median_s": round(statistics.median(values), 2) if values else None,
            "p95_s": round(percentile(values, 0.95), 2) if values else None,
            "samples": len(values),
            "breakdown": {
                "stream_lag_s": None,
                "inference_s": round(last.inference_s, 3) if last else None,
                "publish_s": round(last.publish_s, 3) if last else None,
                "home_assistant_s": (
                    round(last.home_assistant_s, 3)
                    if last and last.home_assistant_s is not None
                    else None
                ),
            },
        }
