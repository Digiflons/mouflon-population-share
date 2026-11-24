"""Second opinion from Google DeepMind's Perch 2.0 (MOUL-54).

When BirdNET is uncertain, or the bird is new or rare, Perch listens to the **same**
3-second window, still in memory, and says whether it hears the same species. Its
agreement is one confirmation step.

- Model: Perch v2, converted to ONNX (no-DFT variant, FP32, all 14,795 classes) and
  run by ONNX Runtime, already in the image as a BirdNET dependency. The ``birdnet``
  library's own Perch needs TensorFlow, which the App image must not contain.
- Files are downloaded when the image is built and checked against
  ``models.lock.json``; the Pi never downloads anything at runtime.
- Perch hears 5 s at 32 kHz: the 3 s window is resampled and repeated to fill 5 s.
  Digital silence (a muted stream) is never sent: Perch gives arbitrary, sometimes
  high scores on all-zero input (seen in CI), so such a window is skipped.
- Taxonomy: BirdNET and Perch labels are matched by scientific name, with a bundled
  alias table for names that differ between the two taxonomies.
- Never blocks: if Perch is off, still loading, short of memory, busy, or does not
  know the species, the step is skipped and confirmation goes on without it.
- The window is only an argument of :meth:`SecondOpinion.ask`: never stored, logged
  or sent anywhere.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from mouflon_population import SAMPLE_RATE

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import numpy as np

log = logging.getLogger(__name__)

PERCH_DIR = "acoustic-models/perch-v2-onnx"
MODEL_FILE = "perch_v2_no_dft_fp32.onnx"
LABELS_FILE = "perch_v2_labels.txt"
PERCH_LABEL = "Perch v2 ONNX fp32 (no-DFT)"
PERCH_CLASSES = 14_795
PERCH_SAMPLE_RATE = 32_000
PERCH_SAMPLES = 160_000
# Perch's logits are not probabilities: thousands of classes are above 0 even on
# noise (top logit about 7 on noise, 9-13 for birds really present in the test
# recording, measured in CI). Its score for a species is therefore
# sigmoid(logit - LOGIT_OFFSET), and Perch "agrees" at AGREE_SCORE or more (the App
# option perch_agreement; 0.70 means a logit of about 8.85). Provisional
# calibration from the test recording, to be redone with real garden data.
LOGIT_OFFSET = 8.0
AGREE_SCORE = 0.70
# Fallbacks: Perch is skipped rather than slowing Home Assistant down.
# Rate limit: at most MAX_PER_MINUTE runs in any 60 s. Silent checks (birds below
# the publication threshold) come last: only while fewer than SILENT_MAX_PER_MINUTE
# runs happened in the last minute and the load is at most SILENT_MAX_LOAD per core.
MAX_PER_MINUTE = 6
SILENT_MAX_PER_MINUTE = 3
SILENT_MAX_LOAD = 1.0
# Free memory needed to load: 2 x the model file plus headroom for the Pi.
MEMORY_FACTOR = 2.0
HEADROOM_MB = 300
MAX_LOAD_PER_CPU = 1.5
THREADS = 2


@dataclass(frozen=True)
class Opinion:
    verdict: str  # "agree", "disagree" or "skipped:<reason>"
    score: float | None = None
    seconds: float | None = None


def parse_labels(text: str) -> list[str]:
    """Scientific names in output order (one per line, optional header)."""
    names = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("inat2024"):
            continue
        name = line.split(",")[0].split("_")[0].strip().strip('"')
        names.append(name)
    return names


# Below this RMS the window is digital silence (about -100 dBFS).
SILENCE_RMS = 1e-5


def is_silent(window: np.ndarray) -> bool:
    import numpy as np

    return float(np.sqrt(np.mean(np.square(window, dtype=np.float64)))) < SILENCE_RMS


def prepare(window: np.ndarray) -> np.ndarray:
    """BirdNET's 48 kHz window as Perch's input: 32 kHz, 5 s, batch of one.

    The 3 s are repeated to fill 5 s: zero padding is out of Perch's training
    distribution and skews its scores.
    """
    import numpy as np
    from scipy.signal import resample_poly

    gcd = math.gcd(PERCH_SAMPLE_RATE, SAMPLE_RATE)
    audio = resample_poly(
        np.asarray(window, dtype=np.float32),
        PERCH_SAMPLE_RATE // gcd,
        SAMPLE_RATE // gcd,
    ).astype(np.float32)[:PERCH_SAMPLES]
    return np.resize(audio, PERCH_SAMPLES).astype(np.float32)[None, :]


ALIASES_FILE = "perch-aliases.json"


def load_aliases(root: Path) -> dict[str, str]:
    """BirdNET name -> Perch name, for species the two taxonomies name differently."""
    try:
        return json.loads((root / ALIASES_FILE).read_text(encoding="utf-8"))["aliases"]
    except (OSError, ValueError, KeyError):
        log.warning("Second opinion: no alias table, exact names only")
        return {}


def available_mb() -> float | None:
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None


def load_per_cpu() -> float:
    try:
        return os.getloadavg()[0] / (os.cpu_count() or 1)
    except OSError:
        return 0.0


def _onnx_session(path: Path):
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = THREADS
    options.inter_op_num_threads = 1
    return ort.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )


class SecondOpinion:
    def __init__(
        self,
        model_dir: Path,
        aliases: dict[str, str] | None = None,
        agree_score: float = AGREE_SCORE,
        session_factory: Callable[[Path], object] = _onnx_session,
        memory: Callable[[], float | None] = available_mb,
        load: Callable[[], float] = load_per_cpu,
    ):
        self.model_dir = model_dir
        self.aliases = aliases or {}
        self.agree_score = agree_score
        self._session_factory = session_factory
        self._memory = memory
        self._load = load
        self._session = None
        self._index: dict[str, int] = {}
        self._lock = threading.Lock()
        self._runs: list[float] = []
        self.status = "loading"

    @property
    def ready(self) -> bool:
        return self._session is not None

    def start(self) -> threading.Thread:
        """Loads the model in the background: listening starts without waiting."""
        thread = threading.Thread(target=self.load_model, name="perch", daemon=True)
        thread.start()
        return thread

    def load_model(self) -> None:
        model = self.model_dir / MODEL_FILE
        labels = self.model_dir / LABELS_FILE
        if not model.is_file() or not labels.is_file():
            self.status = "unavailable"
            log.warning("Second opinion: Perch files missing, step skipped")
            return
        needed = MEMORY_FACTOR * model.stat().st_size / 1_048_576 + HEADROOM_MB
        free = self._memory()
        if free is not None and free < needed:
            self.status = "memory"
            log.warning(
                "Second opinion: %.0f MB free, Perch needs about %.0f MB: step skipped",
                free,
                needed,
            )
            return
        names = parse_labels(labels.read_text(encoding="utf-8"))
        if len(names) != PERCH_CLASSES:
            self.status = "error"
            log.warning("Second opinion: unexpected Perch labels (%d)", len(names))
            return
        started = time.monotonic()
        try:
            session = self._session_factory(model)
        except Exception as error:
            self.status = "error"
            log.warning("Second opinion: Perch could not load: %s", error)
            return
        self._index = {name: i for i, name in enumerate(names)}
        self._session = session
        self.status = "ready"
        log.info(
            "Second opinion ready: %s (%.1f s to load)",
            PERCH_LABEL,
            time.monotonic() - started,
        )

    def index_of(self, scientific: str) -> int | None:
        found = self._index.get(scientific)
        if found is None and scientific in self.aliases:
            found = self._index.get(self.aliases[scientific])
        return found

    def _allowed(self, silent: bool) -> bool:
        now = time.monotonic()
        self._runs = [t for t in self._runs if now - t < 60]
        load = self._load()
        if silent:
            return len(self._runs) < SILENT_MAX_PER_MINUTE and load <= SILENT_MAX_LOAD
        return len(self._runs) < MAX_PER_MINUTE and load <= MAX_LOAD_PER_CPU

    def _skip_reason(self, window: np.ndarray, index: int | None) -> str | None:
        if self._session is None:
            return self.status
        if index is None:
            return "unknown_species"
        if is_silent(window):
            return "silence"
        return None

    def ask(self, window: np.ndarray, scientific: str, silent: bool = False) -> Opinion:
        index = self.index_of(scientific) if self._session is not None else None
        if (reason := self._skip_reason(window, index)) is not None:
            return Opinion(f"skipped:{reason}")
        if not self._lock.acquire(blocking=False):
            return Opinion("skipped:busy")
        if not self._allowed(silent):
            self._lock.release()
            return Opinion("skipped:busy")
        started = time.monotonic()
        self._runs.append(started)
        try:
            logits = self._session.run(["label"], {"inputs": prepare(window)})[0][0]
        except Exception as error:
            log.warning("Second opinion failed on one window: %s", error)
            return Opinion("skipped:error")
        finally:
            self._lock.release()
        seconds = time.monotonic() - started
        score = 1.0 / (1.0 + math.exp(LOGIT_OFFSET - float(logits[index])))
        verdict = "agree" if score >= self.agree_score else "disagree"
        return Opinion(verdict, round(score, 3), round(seconds, 3))
