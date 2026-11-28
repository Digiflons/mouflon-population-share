# AGENTS.md

Instructions for every coding agent working in this repository (Claude Code reads it through `CLAUDE.md`). It wins over any generic agent instructions.

## The project

**Mouflon Population** detects birds: BirdNET listens to the microphones of outdoor cameras and reports detections to Home Assistant on a Raspberry Pi, with an optional dedicated screen. It started as an import of BirdNET-Analyzer (see `UPSTREAM.md`). Architecture: `docs/architecture/README.md`. Security: `docs/security.md`.

The owner **does not code**. Everything reported to the owner is in plain language, without code.

## How the team works

- The work is run by the product team (`.claude/agents/`): product-lead, architect, security-engineer, designer, developer, test-engineer, docs-writer.
- Every piece of work has a shared work file `docs/work/<yyyy-mm-dd>-<slug>.md` made from `docs/work/TEMPLATE.md`. Read it fully before acting; write only your own section plus **Blockers**.
- A new architecture is its own sprint, closed only when the owner is satisfied.
- Work is tracked in Jira project **MOUL** (epics, stories and bugs). Reference the Jira key in work files and commit messages.
- No visual design work for now; the designer is involved only when a functional screen strictly needs it. The screen device is bought after the proof of concept, so everything stays device-agnostic. **Exception (owner's decision 2026-11-22, MOUL-56):** a demo e-ink screen (renderer, PNG + HTML preview, Home Assistant image entities) is built now as a preview environment, with the designer involved.

## Hard rules

1. **Branches:** work on `staging` (or a branch merged into `staging`). Never push to `main`, never force-push, never deploy to production or publish an image/package without the owner's explicit yes.
2. **Secrets:** never ask for, write, log or commit a secret (camera passwords, RTSP URLs with credentials, MQTT logins, Home Assistant tokens). The owner pastes secrets themselves into Home Assistant or GitHub settings.
3. **Privacy: no audio is ever kept (owner's decision, 2026-11-21).** Sound exists only in memory, 3 seconds at a time, and is dropped after analysis. Never write it to disk, logs, history, backups or messages, never send it anywhere, and never add a "bird clip" feature. The only stored data is the detection log: species, confidence, source, time. No new cloud service (no Cloudflare for this project, confirmed by the owner): remote viewing only through the owner's existing Home Assistant Cloud. No telemetry. Changing any of this needs the owner's new decision and a security review.
4. **Audio sources are swappable and battery-safe.** The proof of concept uses battery cameras behind a hub. Every source is a plug-in behind the same interface, and battery sources must respect the battery stop threshold, so they never drain a camera.
5. **Security gate:** anything touching audio, network, secrets, Home Assistant access or dependencies goes through the security-engineer. Open High/Critical findings block the release. Apply Aikido's recommendations, or record in `docs/security.md` why one is a false positive.
6. **Docs ship with the code:** update the affected docs in the same commit, and re-render the diagrams (`python scripts/render_diagrams.py`); the rendered files in `docs/diagrams/` are committed.
7. **Licences:** keep `LICENSE` (MIT, BirdNET team) and `UPSTREAM.md`. The BirdNET 2.4 and geo models are non-commercial only (CC BY-NC-SA 4.0); the 3.0 acoustic model is Apache 2.0 with an acceptable use policy. This is a personal, non-commercial project (confirmed by the owner); no commercial use without a new licence review.
8. **Stack:** Python for the detector (see architecture §3.8 for why the team's standard React/Hono/Cloudflare stack does not apply here). No Cloudflare for this project for now. Do not add a front-end framework or a cloud service without an architecture decision.
9. **Do not remove large parts of the imported code** (GUI, training, docs) without the architect's agreement recorded in a work file.
10. **Describe the product generically (MOUL-49).** Docs, comments, tests, sample data, diagrams and commit messages never contain details about the owner's home, devices (makes, models, names), network, location, employer or people. Write "battery cameras behind a hub", "a Raspberry Pi", "Camera 1", "Jira project MOUL". `app/DOCS.md` is shown to every Home Assistant administrator: it holds only what a household user needs; installation and internals go in `docs/install.md` and the other repository docs.

## Technical facts about the codebase

### Setup and checks

```
pip install -e .[dev]                      # ruff, pytest, docs tooling
git submodule update --init --recursive    # test audio (tests/data), needed by most tests
ruff check . && ruff format --check .
python -m pytest
```

CI (`.github/workflows/ci.yml`) also installs the `embeddings,train,gui-tests` extras and runs `pip-audit`.

- **Test audio is a git submodule** (`tests/data` → `birdnet-team/birdnet-test-data`, pinned commit). Without it most tests cannot run.
- **Models download on first use** from the `birdnet` library into the folder named by `BIRDNET_APP_DATA` (zenodo.org, tuc.cloud, github.com). Roughly 120 MB acoustic, 35 MB geo, 380 MB Perch v2; the 3.0 acoustic ONNX model is ~345 MB. Tests have a 120 s timeout that a cold download can exceed, so download first:
  `python -c "import birdnet; birdnet.load('acoustic', '3.0', 'onnx', lang='en_us'); birdnet.load('acoustic', '2.4', 'tf', lang='en_us')"`
  Some sandboxes cannot reach zenodo.org; then the model-dependent tests fail and must be run in CI.
- **The ruff version is pinned in two places**: the `[dev]` extra in `pyproject.toml` and `.github/workflows/lint.yml`. Bump both together. Do not widen the ruff `select`/`ignore` lists to make a fix pass.

### The Home Assistant App (`app/`)

- `app/` is the App folder the Home Assistant Supervisor builds on the Pi (`config.yaml`, `Dockerfile`, `run.sh`, `DOCS.md`, `translations/`). `repository.yaml` at the root makes the repository an App repository. **Nothing is published**: no registry image.
- Installation steps (token, repository address, hub set-up, dashboard) are in `docs/install.md`, not in `app/DOCS.md`.
- The repository is **private**. Home Assistant reads it with a fine-grained, read-only, expiring token the owner creates and pastes themselves. Docs show only the `<TOKEN>` placeholder; never write a real token anywhere.
- **Demo mode** (`demo.py`, MOUL-41) invents detections for display only: never write them to the bird log, keep `demo: true` and the "Démo" prefix on everything it publishes, and never let it run alongside test mode or enabled sources.
- Listening defaults to sunrise–sunset (`sun.sun`, MOUL-39). The battery guard applies in every listening mode.
- Python package `app/src/mouflon_population/`. It uses the `birdnet` library directly (BirdNET 2.4 FP16 on LiteRT), **never** `birdnet_analyzer`, which pulls in TensorFlow. CI fails if `tensorflow`, `gradio`, `webview` or `birdnet_analyzer` can be imported in the image.
- Dependencies: edit `app/requirements.txt`, then regenerate the hash lock: `uv pip compile app/requirements.txt --universal --python-version 3.13 --generate-hashes -o app/requirements.lock`.
- Pins: the base image digest (`app/Dockerfile`), the e2e image digests (`tests/e2e/compose.yaml`) and the model fingerprints (`app/models.lock.json`) are refreshed with the manual **Refresh pins** workflow, then reviewed and committed.
- Tests: `tests/mouflon/` (unit tests, plus real-BirdNET tests that skip when the models cannot be downloaded), and `tests/e2e/`, run by the **App image** workflow (Home Assistant + Mosquitto + App in test mode).
- Preview for the owner: `PYTHONPATH=app/src python -m mouflon_population.preview --input app/samples/detections.json --output docs/preview/index.html --title "Mouflon Population — aperçu (données d'exemple)"`. A test checks that the committed page matches.
- **Reference songs are not garden audio (MOUL-48).** `app/library/songs/` holds third-party reference recordings of each species (xeno-canto, credited). They are the only audio the App ever writes, only to `/media/mouflon_population/songs/`. Never mix them with sound from the cameras, which is never kept.
- The bird library (`app/library/`) is built by the "Bird illustrations" workflow (`tools/illustrations/`) and installed with `tools/illustrations/install.py`. The Pi never fetches images or songs from the internet. Since 0.6.0 the App bundles the **full library** (`library-build/build/`, owner's approval 2026-11-23), installed with `--extra library-build/demo-pack` so demo species missing from the regional list (the hoopoe) keep their plate. Every multi-species plate needs a reviewed box in `crops.json` (tied to the exact Commons file), otherwise `install.py` skips it. The library workflow never prints the Wikimedia contact (a GitHub secret, sent only to Wikimedia).
- **Analytics table (MOUL-51):** `analytics.sqlite` in the App's data folder holds real garden detections only, with their final status (confirmed / withdrawn). It is never purged by the bird-log retention, demo and test detections never enter it (tests enforce this), it holds text only, and no copy ever leaves the Pi without a new owner decision and a security review.
- The e-ink demo screen (`screen.py`, MOUL-56) uses only the bundled OFL fonts in `app/fonts/` and renders locally; it refreshes slowly, with no animation. Whenever the layout changes, regenerate `docs/screen-preview/` (PNG + self-contained `preview.html`) in the same commit. The frame never shows a camera or source name. Live preview: the VS Code task "Aperçu écran e-ink" (`tools/screen_preview/run.sh`, MOUL-57) watches the renderer and regenerates the preview on every save; still commit the regenerated files.
- **Language (owner's decisions 2026-11-22 and 2026-11-28):** the user interface and bird names are bilingual, French by default and English available through the `language` setting: put every household-facing string in `i18n.py` and `app/translations/` (French and English), never inline. **Everything else is English:** all documentation, `app/CHANGELOG.md`, the App documentation tab (`app/DOCS.md`), code comments, logs and commit messages. A French UI string quoted in a doc may stay quoted, with an English explanation. Entity ids are pinned with `default_entity_id`; do not rename them.
- **Confirmation cross-checks (MOUL-54, MOUL-55, 0.7.0):** Perch v2 runs as ONNX on ONNX Runtime (`second_opinion.py`), never through the `birdnet` library's Perch (it needs TensorFlow). Its files come from a pinned Hugging Face revision (`models.PERCH_REVISION`) and are checked against `app/models.lock.json`. It gets the window only as a function argument. The Belgian GBIF weekly statistics, Perch aliases and manifest live in `app/crosscheck/`, built by the "Cross-check data" workflow (`tools/crosscheck/`), which uploads them for review and never commits; the Pi never queries GBIF. Score bands and thresholds are App options (architecture §11).
- Firm rule in code: windows of sound are local variables only. Never add a file, log, MQTT or database path for audio. `tests/mouflon` and the e2e test check this.

### Package layout (imported BirdNET-Analyzer)

- `birdnet_analyzer` wraps the `birdnet` library, which does the inference.
- Feature subpackages (`analyze/`, `embeddings/`, `search/`, `species/`, `segments/`, `train/`) follow `core.py` (public API, re-exported in `__init__.py`) + `cli.py` + `__main__.py`. `evaluation/` is different: `main()` in `__init__.py`, logic under `assessment/` and `preprocessing/`.
- `params.py` turns the `*-params.csv` files a run writes back into keyword arguments. `logs.py` leaves logging set-up to the entry points (the package only adds a `NullHandler`).
- The GUI is a Gradio app in a pywebview window (`gui/`), with one translation file per language in `lang/`. It is **not** part of the Pi App (security finding H1).
- **Packaging is an allow-list**: `[tool.setuptools]` `packages` / `package-data` decide what ships; a new subpackage or data file must be added there. `.dockerignore` is separate.
- `settings.APPDIR` is a per-user data folder (`BirdNET-Analyzer-GUI`) holding GUI state and logs outside the checkout.

### Inherited conventions worth keeping

- GUI modules must not import `webview` or `plotly` at import time (the GUI test environment has only gradio).
- Translations are all-or-nothing: a new UI string goes into every `lang/*.json` with a real translation (`tests/gui/test_language.py` enforces it).
- Comments only when the code cannot say it (a constraint, a non-obvious why, a measured value).
