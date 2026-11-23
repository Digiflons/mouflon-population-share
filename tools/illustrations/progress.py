"""Live progress lines for the GitHub log, and totals for the run summary.

Prints only species names and counts: never a URL, header or the User-Agent.
"""

from __future__ import annotations

import os
import time


class Progress:
    def __init__(self, total: int, every: int = 10, clock=time.monotonic):
        self.total = total
        self.every = every
        self.clock = clock
        self.started = clock()
        self.done = 0
        self.plates = 0
        self.songs = 0
        self.failed = 0
        self.not_attempted = 0

    def species(
        self,
        scientific: str,
        plate: str | None,
        song: bool,
        outcome: str | None = None,
    ) -> str:
        """Record one species and print its line.

        plate: book name, or None. outcome: None, "failed" (throttled or
        unreachable: retry later) or "not attempted" (time limit). Only a species
        with no plate on Commons is "missing".
        """
        self.done += 1
        self.plates += plate is not None
        self.songs += song
        self.failed += outcome == "failed"
        self.not_attempted += outcome == "not attempted"
        if plate:
            plate_text = f"found ({plate})"
        elif outcome == "failed":
            plate_text = "failed, retry later"
        elif outcome == "not attempted":
            plate_text = "not attempted (time limit)"
        else:
            plate_text = "missing"
        line = (
            f"[{self.done}/{self.total}] {scientific} — plate: {plate_text}"
            f" | song: {'found' if song else 'missing'}"
        )
        print(line, flush=True)
        if self.done % self.every == 0 or self.done == self.total:
            print(self.totals(), flush=True)
        return line

    def totals(self) -> str:
        elapsed = self.clock() - self.started
        left = self.total - self.done
        estimate = elapsed / self.done * left if self.done else 0
        return (
            f"plates {self.plates}/{self.done}, failed {self.failed}, "
            f"songs {self.songs}/{self.done}, "
            f"elapsed {elapsed / 60:.0f} min, ~{estimate / 60:.0f} min remaining"
        )

    def summary(self, extra: list[str] = ()) -> str:
        lines = [
            "## Bird library build",
            "",
            f"- Species processed: {self.done}/{self.total}",
            f"- With a plate: {self.plates}",
            f"- With a reference song: {self.songs}",
            f"- Elapsed: {(self.clock() - self.started) / 60:.0f} min",
            *extra,
        ]
        text = "\n".join(lines) + "\n"
        path = os.environ.get("GITHUB_STEP_SUMMARY")
        if path:
            with open(path, "a", encoding="utf-8") as summary:
                summary.write(text)
        return text
