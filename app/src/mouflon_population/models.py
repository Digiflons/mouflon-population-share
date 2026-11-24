"""Download the models into the image and check their fingerprints (MOUL-16, MOUL-54).

BirdNET 2.4 (acoustic and geo) comes through the ``birdnet`` library; Perch v2 (ONNX)
comes from a pinned revision of its Hugging Face repository. Neither download is
trusted on its own: every model file must match the SHA-256 recorded in
``models.lock.json``, otherwise the image build fails. The Pi never downloads a
model at runtime.

    python -m mouflon_population.models download
    python -m mouflon_population.models download --only perch
    python -m mouflon_population.models verify --lock models.lock.json
    python -m mouflon_population.models verify --lock models.lock.json --print
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from mouflon_population.second_opinion import LABELS_FILE, MODEL_FILE, PERCH_DIR

MODEL_DIRS = ("acoustic-models/v2.4/tf", "geo-models/v2.4/tf", PERCH_DIR)
SKIP_NAMES = {".download.lock"}
# Perch v2 converted to ONNX (Apache-2.0), at a fixed revision of the repository.
PERCH_REVISION = "5097dffb20f9d4157ee165f4c0b54c4e74d6daba"
PERCH_BASE_URL = (
    f"https://huggingface.co/tphakala/Perch-v2-Models/resolve/{PERCH_REVISION}/full/"
)
PERCH_FILES = (MODEL_FILE, LABELS_FILE)


def app_data() -> Path:
    from birdnet.utils.local_data import get_birdnet_app_data_folder

    return Path(get_birdnet_app_data_folder())


LOCK_FILE = Path(__file__).resolve().parents[2] / "models.lock.json"
DOWNLOAD_ATTEMPTS = 4


def _lock_entries(lock: Path) -> dict[str, str]:
    for candidate in (lock, Path("/opt/mouflon/models.lock.json")):
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))["files"]
    return {}


def _fetch(url: str, partial: Path) -> None:
    import shutil
    import urllib.request

    request = urllib.request.Request(
        url, headers={"User-Agent": "mouflon-population-build"}
    )
    with (
        urllib.request.urlopen(request, timeout=120) as response,
        partial.open("wb") as out,
    ):
        shutil.copyfileobj(response, out, length=1 << 20)
        expected = response.headers.get("Content-Length")
    if expected is not None and partial.stat().st_size != int(expected):
        raise OSError(f"incomplete download ({partial.stat().st_size} of {expected})")


def download_perch(root: Path, lock: Path = LOCK_FILE) -> None:
    """Fetch the Perch files, retrying until each matches its pinned fingerprint.

    A connection cut short can end "cleanly" with a truncated file; every file
    is therefore checked against ``models.lock.json`` before it is kept.
    """
    expected = _lock_entries(lock)
    target = root / PERCH_DIR
    target.mkdir(parents=True, exist_ok=True)
    for name in PERCH_FILES:
        path = target / name
        digest = expected.get(f"{PERCH_DIR}/{name}")
        if path.is_file() and (digest is None or _sha256(path) == digest):
            continue
        partial = path.with_suffix(path.suffix + ".part")
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            try:
                _fetch(PERCH_BASE_URL + name, partial)
                if digest is None or _sha256(partial) == digest:
                    partial.replace(path)
                    break
                problem = "fingerprint mismatch"
            except OSError as error:
                problem = str(error)
            partial.unlink(missing_ok=True)
            print(
                f"Perch download {name}, attempt {attempt}: {problem}", file=sys.stderr
            )
        else:
            raise RuntimeError(f"could not download {name} with the pinned fingerprint")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(language: str = "en_us", only: str = "all") -> None:
    if only in ("all", "perch"):
        download_perch(app_data())
    if only == "perch":
        return
    import birdnet

    from mouflon_population.detector import MODEL_PRECISION, MODEL_VERSION

    birdnet.load(
        "acoustic",
        MODEL_VERSION,
        "tf",
        precision=MODEL_PRECISION,
        lang=language,
        library="litert",
    )
    birdnet.load("geo", MODEL_VERSION, "tf", lang=language, library="litert")


def fingerprints(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for model_dir in MODEL_DIRS:
        base = root / model_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and not any(p in SKIP_NAMES for p in path.parts):
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                result[path.relative_to(root).as_posix()] = digest
    return result


def verify(root: Path, expected: dict[str, str]) -> list[str]:
    actual = fingerprints(root)
    problems = []
    if not expected:
        problems.append("the lock file lists no model files")
    for name, digest in expected.items():
        if name not in actual:
            problems.append(f"missing: {name}")
        elif actual[name] != digest:
            problems.append(f"fingerprint mismatch: {name}")
    problems.extend(
        f"not in the lock file: {name}" for name in sorted(set(actual) - set(expected))
    )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("download")
    fetch.add_argument("--only", choices=("all", "birdnet", "perch"), default="all")
    check = sub.add_parser("verify")
    check.add_argument("--lock", type=Path, required=True)
    check.add_argument(
        "--print", action="store_true", help="print the actual fingerprints"
    )
    args = parser.parse_args(argv)

    if args.command == "download":
        download(only=args.only)
        return 0

    root = app_data()
    expected = json.loads(args.lock.read_text(encoding="utf-8"))["files"]
    problems = verify(root, expected)
    if args.print or problems:
        actual = fingerprints(root)
        print(json.dumps({"files": actual}, indent=2, sort_keys=True))
        if os.environ.get("GITHUB_ACTIONS"):
            for name, digest in actual.items():
                print(f"::notice title=model fingerprint::{name} {digest}")
    for problem in problems:
        print(f"Model check failed: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
