"""Audio sources: swappable plug-ins behind one interface (MOUL-13, MOUL-19, MOUL-20).

A source yields 3-second windows of mono 48 kHz float32 sound, kept in memory only.
Nothing here writes audio anywhere.

- :class:`StreamSource` reads any stream ffmpeg can open (a camera hub's
  RTSP, a mains camera, a network microphone) and keeps the sound track only.
- :class:`FileSource` replays a recorded file (test mode).

:func:`reconnecting_windows` wraps a source with reconnection and a growing delay.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

import numpy as np

from mouflon_population import SAMPLE_RATE, WINDOW_SAMPLES, masking

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Iterator

log = logging.getLogger(__name__)

BYTES_PER_WINDOW = WINDOW_SAMPLES * 4  # float32
# ffmpeg's socket timeout for RTSP, in microseconds: a sleeping battery camera
# that does not answer must not block the reader forever.
RTSP_TIMEOUT_US = 15_000_000


class SourceError(RuntimeError):
    pass


class AudioSource(Protocol):
    name: str

    def windows(self, stop: threading.Event) -> Iterator[np.ndarray]: ...


def url_with_login(url: str, username: str, password: str) -> str:
    if not username:
        return url
    parts = urlsplit(url)
    login = quote(username, safe="")
    if password:
        login += ":" + quote(password, safe="")
    netloc = f"{login}@{parts.hostname or ''}"
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def ffmpeg_command(url: str) -> list[str]:
    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error"]
    if url.startswith(("rtsp://", "rtsps://")):
        command += ["-rtsp_transport", "tcp", "-timeout", str(RTSP_TIMEOUT_US)]
    command += [
        "-i",
        url,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "f32le",
        "pipe:1",
    ]
    return command


class StreamSource:
    def __init__(self, name: str, url: str, username: str = "", password: str = ""):
        self.name = name
        self._url = url_with_login(url, username, password)
        masking.register_secret(password)

    def windows(self, stop: threading.Event) -> Iterator[np.ndarray]:
        if shutil.which("ffmpeg") is None:
            raise SourceError("ffmpeg is not installed")
        process = subprocess.Popen(
            ffmpeg_command(self._url),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert process.stdout is not None
        try:
            while not stop.is_set():
                data = _read_exactly(process.stdout, BYTES_PER_WINDOW)
                if len(data) < BYTES_PER_WINDOW:
                    break
                yield np.frombuffer(data, dtype="<f4").copy()
                del data
        finally:
            process.kill()
            _, err = process.communicate(timeout=10)
            if not stop.is_set():
                message = err.decode(errors="replace").strip().splitlines()
                detail = message[-1] if message else f"exit code {process.returncode}"
                raise SourceError(f"stream ended: {masking.mask(detail)}")


def _read_exactly(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


class FileSource:
    """Replays a recorded file as if it were a live source (test mode)."""

    def __init__(self, name: str, path: str | Path, realtime: bool = True):
        self.name = name
        self.path = Path(path)
        self.realtime = realtime

    def windows(self, stop: threading.Event) -> Iterator[np.ndarray]:
        audio = load_mono_48k(self.path)
        for start in range(0, len(audio) - WINDOW_SAMPLES + 1, WINDOW_SAMPLES):
            if stop.is_set():
                return
            yield audio[start : start + WINDOW_SAMPLES]
            if self.realtime and stop.wait(WINDOW_SAMPLES / SAMPLE_RATE):
                return


def load_mono_48k(path: Path) -> np.ndarray:
    import soundfile as sf
    from scipy.signal import resample_poly

    audio, rate = sf.read(str(path), dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    if rate != SAMPLE_RATE:
        gcd = np.gcd(rate, SAMPLE_RATE)
        mono = resample_poly(mono, SAMPLE_RATE // gcd, rate // gcd).astype("float32")
    return mono


def reconnecting_windows(
    source: AudioSource,
    stop: threading.Event,
    on_state: Callable[[str], None] = lambda _state: None,
    first_delay_s: float = 2.0,
    max_delay_s: float = 120.0,
    reconnect: bool = True,
) -> Iterator[np.ndarray]:
    """Yield windows from ``source``, reconnecting with a growing delay on failure."""
    delay = first_delay_s
    while not stop.is_set():
        on_state("connecting")
        received = False
        try:
            for window in source.windows(stop):
                if not received:
                    received = True
                    delay = first_delay_s
                    on_state("listening")
                yield window
        except Exception as error:
            log.warning("%s: %s", source.name, masking.mask(str(error)))
        if stop.is_set() or not reconnect:
            return
        on_state("offline")
        log.info("%s: reconnecting in %.0f s", source.name, delay)
        if stop.wait(delay):
            return
        delay = min(delay * 2, max_delay_s)
