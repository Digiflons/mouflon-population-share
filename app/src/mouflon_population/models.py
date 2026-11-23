"""Download the BirdNET models into the image and check their fingerprints (MOUL-16).

The ``birdnet`` library does not verify the 2.4 model downloads, so the image build
does: every model file must match the SHA-256 recorded in ``models.lock.json``,
otherwise the build fails.

    python -m mouflon_population.models download
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

MODEL_DIRS = ("acoustic-models/v2.4/tf", "geo-models/v2.4/tf")
SKIP_NAMES = {".download.lock"}


def app_data() -> Path:
    from birdnet.utils.local_data import get_birdnet_app_data_folder

    return Path(get_birdnet_app_data_folder())


def download(language: str = "en_us") -> None:
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
    sub.add_parser("download")
    check = sub.add_parser("verify")
    check.add_argument("--lock", type=Path, required=True)
    check.add_argument(
        "--print", action="store_true", help="print the actual fingerprints"
    )
    args = parser.parse_args(argv)

    if args.command == "download":
        download()
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
