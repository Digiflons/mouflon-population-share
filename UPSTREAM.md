# Where this code comes from

This repository started as a copy of **BirdNET-Analyzer**
(https://github.com/birdnet-team/BirdNET-Analyzer), developed by the K. Lisa Yang Center
for Conservation Bioacoustics (Cornell Lab of Ornithology) and Chemnitz University of Technology.

- Imported from upstream commit `897c6376a69e70da949b7233dfaaaf4d58db5d63` (branch `main`, 2026-11-20)
- Imported on 2026-11-21 into the Mouflon Population repository
- Only the current code was imported, not the upstream git history

## Licences
- **Code:** MIT, copyright (c) 2024 birdnet-team. See `LICENSE`. The notice must stay with the code.
- **BirdNET models:** the 2.4 acoustic model and the geo models are CC BY-NC-SA 4.0, for **non-commercial use only**
  (research and education count as non-commercial). The 3.0 acoustic model is Apache 2.0 with the BirdNET team's
  acceptable use policy (per upstream's README, checked 2026-11-21). Any commercial use, including under a company,
  needs a separate review or agreement with the BirdNET team.
- **Test audio** (`tests/data`) is the upstream submodule `birdnet-team/birdnet-test-data`, pinned at `0545aad`.

## What we changed at takeover (2026-11-21)
- Upstream release workflows (PyPI, winget, Linux packages, docs site, image publishing) removed: they published
  under the BirdNET team's names. Tests, lint and the Docker build check remain.
- Upstream agent instructions (`AGENTS.md`, `CLAUDE.md`, `.github/copilot-instructions.md`) replaced by ours;
  their technical facts were kept in `AGENTS.md`.
- Upstream README moved to `docs/upstream-README.md`.
