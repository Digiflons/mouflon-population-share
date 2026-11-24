"""Measure Perch v2 (ONNX) on this machine and check it agrees with BirdNET (MOUL-54).

Runs in GitHub Actions on x86 and arm64 runners. Reports, as workflow notices:
load time, peak memory, time per 3-second window with 1, 2 and 4 threads, and for
every BirdNET detection in the bundled test recording, Perch's score and rank.

    PYTHONPATH=app/src python tools/crosscheck/benchmark_perch.py \\
        app/example/soundscape-60s.flac
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def notice(title: str, text: str) -> None:
    print(text)
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice title={title}::{text}")


def windows(path: Path) -> list[np.ndarray]:
    import soundfile
    from mouflon_population import SAMPLE_RATE

    audio, rate = soundfile.read(path, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if rate != SAMPLE_RATE:
        from scipy.signal import resample_poly

        audio = resample_poly(audio, SAMPLE_RATE, rate).astype("float32")
    size = 3 * SAMPLE_RATE
    return [audio[i : i + size] for i in range(0, len(audio) - size + 1, size)]


def rss_mb() -> float:
    with open("/proc/self/status", encoding="ascii") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return 0.0


def describe(opinion, chunks) -> None:
    """Perch's top classes on real windows, quiet noise and loud noise."""
    import numpy as np
    from mouflon_population import second_opinion as so

    names = {i: n for n, i in opinion._index.items()}
    rng = np.random.default_rng(1)
    cases = {
        "window 0": chunks[0],
        "window 1": chunks[1],
        "noise 3e-3": (rng.standard_normal(chunks[0].shape) * 3e-3).astype("float32"),
        "noise 0.1": (rng.standard_normal(chunks[0].shape) * 0.1).astype("float32"),
        "pink-ish": np.cumsum(rng.standard_normal(chunks[0].shape) * 1e-3).astype(
            "float32"
        ),
    }
    for label, audio in cases.items():
        logits = opinion._session.run(["label"], {"inputs": so.prepare(audio)})[0][0]
        top = np.argsort(logits)[::-1][:6]
        positive = int((logits > 0).sum())
        shifted = logits - logits.max()
        soft = np.exp(shifted) / np.exp(shifted).sum()
        listed = ", ".join(
            f"{names[i]} {logits[i]:.1f} (softmax {soft[i]:.3f})" for i in top
        )
        print(f"{label}: {positive} classes > 0; top: {listed}")


def main() -> int:
    from mouflon_population import second_opinion as so
    from mouflon_population.detector import BirdnetPredictor, filter_detections
    from mouflon_population.models import app_data

    machine = os.uname().machine
    model_dir = app_data() / so.PERCH_DIR
    chunks = windows(Path(sys.argv[1]))
    before = rss_mb()

    timings = {}
    for threads in (1, 2, 4):
        so.THREADS = threads
        opinion = so.SecondOpinion(model_dir, load=lambda: 0.0)
        started = time.monotonic()
        opinion.load_model()
        load_s = time.monotonic() - started
        assert opinion.ready, opinion.status
        opinion.ask(chunks[0], "Turdus migratorius")  # warm-up
        if threads == 1:
            notice(
                f"Perch memory ({machine})",
                f"{rss_mb() - before:.0f} MB more resident memory once Perch is "
                "loaded and has run once",
            )
        runs = []
        for chunk in chunks[:12]:
            started = time.monotonic()
            opinion._session.run(["label"], {"inputs": so.prepare(chunk)})
            runs.append(time.monotonic() - started)
        timings[threads] = statistics.median(runs)
        notice(
            f"Perch speed ({machine})",
            f"{threads} thread(s): {timings[threads]:.2f} s per window "
            f"(load {load_s:.1f} s)",
        )
        del opinion

    so.THREADS = 2
    opinion = so.SecondOpinion(model_dir, load=lambda: 0.0)
    opinion.load_model()
    describe(opinion, chunks)
    birdnet = BirdnetPredictor("en_us")
    agree = total = 0
    import numpy as np

    for i, chunk in enumerate(chunks):
        raw = opinion._session.run(["label"], {"inputs": so.prepare(chunk)})[0][0]
        soft = np.exp(raw - raw.max())
        soft /= soft.sum()
        for d in filter_detections(birdnet(chunk), 0.2):
            index = opinion.index_of(d.scientific)
            if index is not None:
                rank = int((raw > raw[index]).sum())
                print(
                    f"softmax window {i:2d} {d.scientific:28s} BirdNET "
                    f"{d.confidence:.2f} logit {raw[index]:.1f} softmax "
                    f"{soft[index]:.3f} rank {rank}"
                )
            if d.confidence < 0.5:
                continue
            result = opinion.ask(chunk, d.scientific)
            total += result.verdict != "skipped:unknown_species"
            agree += result.verdict == "agree"
            print(
                f"window {i:2d} {d.scientific:28s} BirdNET {d.confidence:.2f} "
                f"Perch {result.verdict} {result.score}"
            )
    birdnet.close()
    notice(
        f"Perch agreement ({machine})",
        f"Perch agrees on {agree} of {total} BirdNET detections >= 0.5 "
        "in the test recording",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
