"""BirdNET inference on in-memory windows, and the filters applied to its answers.

Filters (MOUL-25, MOUL-26):
- Human sounds and other non-species classes (dog, engine, siren, noise...) are
  dropped here and never stored or published.
- Only detections at or above the confidence threshold are kept.
- With a species list (from the geo model and Home Assistant's home location), only
  species expected at home this time of year are kept.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mouflon_population import SAMPLE_RATE

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable

    import numpy as np

log = logging.getLogger(__name__)

MODEL_VERSION = "2.4"
MODEL_PRECISION = "fp16"
MODEL_LABEL = f"BirdNET {MODEL_VERSION} TFLite {MODEL_PRECISION}"
# BirdNET's own floor; our min_confidence filter is applied on top of it.
MODEL_FLOOR = 0.1


@dataclass(frozen=True)
class Detection:
    scientific: str
    common: str
    confidence: float


def parse_label(label: str) -> tuple[str, str]:
    scientific, _, common = label.partition("_")
    return scientific.strip(), (common or scientific).strip()


def is_non_species(scientific: str, common: str) -> bool:
    """Human sounds and BirdNET's non-species classes (named ``X_X``)."""
    if "human" in scientific.lower() or "human" in common.lower():
        return True
    return scientific.lower() == common.lower() or " " not in scientific


def filter_detections(
    raw: Iterable[tuple[str, float]],
    min_confidence: float,
    allowed_species: Collection[str] | None = None,
    dropped_by_species: list[str] | None = None,
) -> list[Detection]:
    kept: dict[str, Detection] = {}
    for label, confidence in raw:
        scientific, common = parse_label(label)
        if is_non_species(scientific, common):
            continue
        if confidence < min_confidence:
            continue
        if allowed_species is not None and scientific not in allowed_species:
            if dropped_by_species is not None and common not in dropped_by_species:
                dropped_by_species.append(common)
            continue
        previous = kept.get(scientific)
        if previous is None or confidence > previous.confidence:
            kept[scientific] = Detection(
                scientific, common, round(float(confidence), 3)
            )
    return sorted(kept.values(), key=lambda d: d.confidence, reverse=True)


class FilteringDetector:
    """Applies :func:`filter_detections` to a raw ``(label, confidence)`` predictor."""

    def __init__(
        self,
        predict: Callable[[np.ndarray], list[tuple[str, float]]],
        min_confidence: float,
    ):
        self._predict = predict
        self.min_confidence = min_confidence
        self.allowed_species: frozenset[str] | None = None
        self.last_dropped: list[str] = []

    def detect(self, window: np.ndarray) -> list[Detection]:
        """Kept detections; ``last_dropped`` lists birds the species filter removed."""
        self.last_dropped = []
        return filter_detections(
            self._predict(window),
            self.min_confidence,
            self.allowed_species,
            self.last_dropped,
        )


class BirdnetPredictor:
    """BirdNET 2.4 (TFLite, FP16) run by LiteRT: no TensorFlow needed.

    The prediction session stays open, so the model is loaded once. A lock makes
    one predictor safe to share between the sources' threads.
    """

    def __init__(self, language: str = "en_us"):
        import birdnet

        self._model = birdnet.load(
            "acoustic",
            MODEL_VERSION,
            "tf",
            precision=MODEL_PRECISION,
            lang=language,
            library="litert",
        )
        self._session = self._model.predict_session(
            top_k=10,
            n_producers=1,
            n_workers=1,
            batch_size=1,
            default_confidence_threshold=MODEL_FLOOR,
            show_stats=None,
        )
        self._session.__enter__()
        self._lock = threading.Lock()

    def __call__(self, window: np.ndarray) -> list[tuple[str, float]]:
        with self._lock:
            result = self._session.run_arrays([(window, SAMPLE_RATE)])
        rows = result.to_structured_array()
        return [(str(r["species_name"]), float(r["confidence"])) for r in rows]

    def close(self) -> None:
        self._session.__exit__(None, None, None)


def species_for_location(
    latitude: float, longitude: float, week: int, language: str = "en_us"
) -> dict[str, float]:
    """Species the geo model expects at this place and week, with their probability.

    Used by the species filter (MOUL-26) and the regional rarity (MOUL-47).
    """
    import birdnet

    model = birdnet.load("geo", MODEL_VERSION, "tf", lang=language, library="litert")
    result = model.predict(latitude, longitude, week=week, min_confidence=0.03)
    probabilities = {
        parse_label(str(row["species_name"]))[0]: float(row["confidence"])
        for row in result.to_structured_array()
    }
    log.info("Species filter: %d species expected this week", len(probabilities))
    return probabilities
