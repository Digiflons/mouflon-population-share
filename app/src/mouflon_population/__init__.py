"""Mouflon Population: bird detection for Home Assistant, built on BirdNET.

Firm rule: no audio is ever kept. Sound exists only in memory, one window at a time.
"""

__version__ = "0.7.0"

SAMPLE_RATE = 48_000
WINDOW_SECONDS = 3.0
WINDOW_SAMPLES = int(SAMPLE_RATE * WINDOW_SECONDS)
