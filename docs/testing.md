# Testing — Mouflon Population

Owner: test-engineer.

## How to run the tests

```
pip install -e .[dev,embeddings,train,gui-tests]
git submodule update --init --recursive      # test audio
python -c "import birdnet; birdnet.load('acoustic', '3.0', 'onnx', lang='en_us'); birdnet.load('acoustic', '2.4', 'tf', lang='en_us'); birdnet.load('geo', '3.0', 'onnx', lang='en_us')"
ruff check . && ruff format --check .
python -m pytest
pip-audit
```

The same checks run automatically on GitHub for every push to `staging` and `main`: "Tests", "Lint", and "App image", which builds the Home Assistant App for x86 and for the Raspberry Pi (arm64) and runs the end-to-end test with a real Home Assistant and Mosquitto (`tests/e2e/`).

## Confirmation cross-checks — MOUL-54, MOUL-55 (2026-11-23, version 0.7.0)

New tests (`tests/mouflon/test_crosschecks.py`):
- **The rule:**
  - confident and observed locally confirms at once;
  - rarely observed locally needs Perch or a repeat;
  - uncertain and observed locally waits for one more check;
  - Perch alone is not enough for an uncertain, rarely observed bird;
  - skipped checks never block, and an unconfirmed bird is withdrawn when the window ends;
  - a later "skipped" keeps an earlier Perch disagreement;
  - the four steps are in French, with their states and notes.
- **Perch with a fake ONNX session:**
  - the 3 s window is resampled and repeated to fill Perch's 5 s, and digital silence is never sent to Perch;
  - agreement only on a Perch score of 0.70 or more (logit about 8.85); a top rank with a noise-level logit is not agreement;
  - taxonomy aliases work;
  - skipped for an unknown species, a busy Pi, a run already in progress, not enough memory, missing files, wrong labels, or still loading;
  - the rate limit puts silent checks last, and silent checks are skipped first when the Pi is loaded.
- **The service:**
  - Perch hears the very same window object;
  - a sure common bird is confirmed when heard twice, without Perch (or at once when `common_confirm_twice` is off);
  - a sure bird rarely observed locally is cross-checked;
  - a new bird common in Belgium needs no Perch, and a rarely observed one is confirmed by Perch;
  - Perch disagreeing keeps the bird provisional;
  - Perch can be turned off;
  - the top of the unsure zone is a setting, and invalid limits are refused.
- **Silent check (0.20–0.50):**
  - a plausible bird that Perch agrees with is rescued, shown as provisional at 67 % (2 of 3 checks), and confirmed by one more published detection; a low repeat is not enough;
  - Perch below 0.70 drops it quietly, and only the counter changes;
  - a locally rare bird is dropped without asking Perch;
  - the counter resets daily.
- **No window survives the analysis:** no array of the window's size is left in memory, no message mentions audio, and only the database files are written.
- **Local statistics:** the week and its neighbours are used; aliases work; broken files make the check unavailable, not the App; test mode skips the check.
- **Bundled data and pins:**
  - Perch is pinned by a 40-character revision and by SHA-256 fingerprints;
  - the bundled statistics cover 10 years at country level with no coordinates, and common garden birds are "observed" all year;
  - the manifest keeps only CC0 / CC BY records and cites every dataset with a DOI;
  - at most 5 % of the library species are unknown to Perch (3 of 216).
- **Perch download:** a truncated file is fetched again until it matches its pinned fingerprint; a wrong file is refused and deleted.
- **Real Perch** (runs in CI, where the model is downloaded): it agrees with BirdNET on the test recording's chickadee and disagrees on silence. Its first CI run caught a flaw: with the earlier "top 3 classes" rule, Perch "agreed" on pure silence. The rank rule was removed; agreement is now a score of 0.70 or more. The next run showed Perch scoring 0.82 on an all-zero window: the window is now repeated to fill 5 s instead of zero-padded, and digital silence is skipped. The run after that showed a chickadee at 0.88 on quiet noise: Perch's logits are not probabilities, so the score is now `sigmoid(logit − 8)`, calibrated on the test recording (true birds 9–13, noise about 7). The real test checks that quiet noise gives "disagree".

Updated: `test_confirmation_delay.py` (four steps), demo test (the demo shows the four checks with the real tracker).

Measurements (workflow "Cross-check data", 2026-11-23):

| Runner | 1 thread | 2 threads | 4 threads | Extra memory | Agreement with BirdNET (test recording) |
|---|---|---|---|---|---|
| x86 | 0.09 s | 0.09 s | 0.12 s | +585 MB | 4 of 4 |
| arm64 | 0.40 s | 0.21 s | 0.39 s | +559 MB | 4 of 4 |

Perch logits on the test recording (x86): birds really present 9.2–12.9; two doubtful BirdNET detections 8.3 and 6.2; quiet and loud white noise top out at 7.2 and 6.5. With the calibrated score, every 0.20–0.50 detection of a bird really present would be rescued by the silent check, and both doubtful ones dropped.

CI result: Lint, Tests and App image (with the end-to-end test) pass.

## Pre-sharing inspection — 0.6.1 (2026-11-23)

- Internal clean-up only, behaviour identical. The Home Assistant discovery messages were compared byte for byte before and after the refactor, in French and in English (28 messages, identical).
- `tests/mouflon` and `tests/illustrations`: all pass locally (real-BirdNET tests skip in the sandbox); the full suite, lint and the App image with the end-to-end test run on GitHub.

## Provisional birds and detection delay — MOUL-53, MOUL-52 (2026-11-22, version 0.4.0)

New tests (`tests/mouflon/test_confirmation_delay.py`):
- a first-time bird appears at once as provisional, at 50 % with one of two steps done and 15 minutes left. There are no rarity pills and no rare-bird event, and it is listed as provisional and not yet in analytics. A second confident detection 6 minutes later confirms it: 100 %, rarity pills, one rare-bird event, two analytics rows;
- an unconfirmed bird is withdrawn after the window: "withdrawn" status, removed from today's list, no rare-bird event, analytics row "withdrawn" only, nothing in the bird log;
- a weak first detection starts at 0 %;
- the delay sensor holds the last value, median, p95 and the breakdown, and is announced in discovery;
- the median and 95th percentile are computed correctly;
- demo mode shows the provisional and confirmed flow, marked as demo.

## E-ink demo screen and analytics table — MOUL-56, MOUL-51 (2026-11-22, version 0.3.0)

New tests (`tests/mouflon/test_analytics_screen.py`):
- **analytics:**
  - the schema stores year, month, week, status and versions;
  - only "confirmed" or "withdrawn" rows are accepted;
  - the bird-log retention never deletes analytics rows;
  - real confirmed detections are recorded, and the export button writes a CSV with the right row count;
  - **test mode and demo mode never write analytics rows**;
- **screen:**
  - both views render at 480×800 and 1200×1600, with or without a bird;
  - the e-ink preview uses only the six panel colours;
  - the gallery refreshes the screen at most every 10 minutes;
- discovery announces the export button and both screen image entities;
- the screen size setting is validated.

## Bird library, rarity and songs — MOUL-42/45/47/48 (2026-11-22, version 0.2.0)

New unit tests (`tests/mouflon/test_library.py`, plus updates in the demo and service tests):
- the library reads drawings, credits, IUCN status and song ids. Installing the songs writes only the library's clips into the media folder, and only once;
- the gallery sends the last bird's drawing and the six "today" slots, each drawing printed on the taupe paper, and the French "Gravure à venir" card when a drawing is missing; the species list has counts, rarity, credit and song;
- rarity levels and tags: each tag has a label, a short label (12 characters or fewer), an icon and a colour;
- the confirmation rule: a rare candidate is confirmed only by two detections at ≥ 0.75 within 15 minutes; weak or too-distant detections do not count;
- the bird log's 12-month history and today's list (at most 30, most recent first);
- discovery announces the image entities, the rare-bird event and the species attribute;
- demo mode publishes clearly marked demo rarities.

The end-to-end test also checks the drawing image entity, the rare-bird event and the `species` attribute in a real Home Assistant. Library content is not yet bundled (see the work file), so drawings show the placeholder.

## Demo mode — MOUL-41 (2026-11-21)

New tests (`tests/mouflon/test_demo.py` and the settings tests):
- the rhythm (MOUL-50): never night. Over a whole real day, activity never falls below 20 % of the peak, busy waves are at least 4 times the quietest moment, and birds keep coming at 2 a.m.;
- every demo detection and event carries `demo: true`, a "Démo" source and a Belgian species, and the Demo mode sensor is announced and on;
- no demo birds at night;
- **demo data never reaches the real bird log** (the real log is unchanged and no file is created);
- switching demo off resets Home Assistant: the Demo mode sensor goes off, the "Démo" entities are removed, the last bird shows "No bird yet" and the counters show 0;
- the settings refuse demo mode with test mode or with enabled sources;
- "Démo" names become clean entity ids.

The end-to-end test still runs in test mode. Demo mode is covered by the unit tests.

## Bug MOUL-40 — no birds in test mode on the Pi (2026-11-21)

**What happened:** on the owner's Pi, test mode showed 0 detections. The bundled recording is North American, and the species filter (fed by the Belgian home location) dropped every bird. CI missed it because the end-to-end test ran without a home location.

**Fix and new tests:**
- Test mode switches the species filter off and says so in the log.
- A log line now counts and names the detections the filter drops.
- Unit tests cover both. The end-to-end test now runs with a **Belgian home location** and the species filter on, and checks the log line. It would have caught the bug.
- App version 0.1.1, so Home Assistant offers the update.

## Change MOUL-39 — daylight listening (2026-11-21)

New tests: listening follows the sun (above the horizon = listen; below = "outside daylight"; unknown = "paused: sun position unknown"). Invalid listening modes are refused, and every battery pause is labelled "paused: battery …". A service test shows the camera is never opened after sunset. The battery tests still pass unchanged, and the end-to-end test now runs with the daylight default. CI results are in the commit's checks on `staging`.

## Proof-of-concept build — 2026-11-21

App version 0.1.0, commit `132db0a` on `staging`. All three GitHub workflows passed.

| Check | Result | Plain-language meaning |
|---|---|---|
| **Tests** workflow: whole suite (upstream + ours) | **841 passed**, 13 skipped (Windows/macOS only) | Nothing in the imported code broke |
| Our unit tests (`tests/mouflon/`) | 34 pass | Settings, credential masking, sources and reconnection, ffmpeg stream reading, human-sound and non-bird filtering, species filter, battery guard (stop, restart, fast drop, unknown or old reading), listening windows, wind and rain, bird log (only the allowed columns), MQTT messages, preview page, model fingerprints |
| Real BirdNET tests | 2 pass on GitHub (skipped in the sandbox, which cannot download models) | BirdNET 2.4 on LiteRT finds birds in the example recording; the geo model gives a plausible species list for a Belgian garden |
| Test-mode chain without a camera | Pass | Recording → BirdNET → bird log → MQTT → events. The test also proves a low battery never opens the camera |
| Dependency audit (`pip-audit`), including the App's lock file | No known vulnerabilities | |
| **Lint** (ruff check + format) | Pass | |
| **App image**: build for x86 | Pass | |
| Image contents | Pass | No TensorFlow, desktop interface, pywebview or imported BirdNET-Analyzer package in the image; models owned by root, read-only for the App |
| Model fingerprints | Pass (56 files, x86 and arm64) | The image refuses any model file that differs from the recorded fingerprints |
| **End-to-end test**: real Home Assistant 2026.8.1 + Mosquitto + the App in test mode | **Pass** | Home Assistant created `event.mouflon_population_bird_detected`, `sensor.mouflon_population_last_bird` (value "House Finch", with species, confidence, source and time), `sensor.mouflon_population_species_today` (2) and `binary_sensor.mouflon_population_test_recording_listening` (on) |
| The App runs without admin rights | Pass | Its processes run as an unprivileged user, not root |
| No audio written | Pass | The only files the App wrote were its bird log and its settings |
| **App image**: build for arm64 (Raspberry the Pi) | Pass | Same image builds for the Pi's processor |

The example recording comes from North America, so the birds found in the test (House Finch, Black-capped Chickadee) are American. In Belgium the species filter will keep only local birds.

Test loops: 4 rounds on the end-to-end test, all caused by the test script itself, not by the App. Home Assistant's MQTT set-up form needed every field filled in. The App worked from the first run.

**Not testable here, to do on the Pi during the proof of concept (MOUL-37):** the camera hub's RTSP stream and its sound track, waking the battery cameras, the real battery drain, how fast the Pi analyses the sound, and the weather station pause.

## Baseline report — 2026-11-21 (takeover)

Environment: Claude sandbox, Linux x86_64, Python 3.13, BirdNET-Analyzer 3.0.0 at upstream `897c6376`, `birdnet` library 1.5.1, all CI extras installed.

| Check | Result | Plain-language meaning |
|---|---|---|
| Install of the package and all test extras | Pass | The code installs cleanly |
| Test audio (submodule) | **Was broken, fixed** | The import had lost the link to the test recordings; restored at upstream's version `0545aad` (71 MB) |
| `ruff` code checks and formatting (pinned 0.15.10) | Pass (138 files) | Code style is clean |
| Unit and integration tests (818 tests) | **793 passed, 13 skipped, 12 failed** | Everything that could run here passed |
| The 12 failures | All caused by the sandbox network refusing `zenodo.org` | These tests need to download the BirdNET models (from zenodo.org); this sandbox may only reach package registries and GitHub. Not a code problem. They must pass on GitHub CI, which has internet access |
| Dependency vulnerability audit (`pip-audit`) | Pass after fix | Initially 42 known issues in an image library (Pillow) dragged in by the desktop interface; fixed by updating gradio and requiring Pillow 13 |

Failed tests (all with "Tunnel connection failed: 403 … zenodo.org"): 11 in `tests/analyze/test_analyze.py` (full analyses of the example recording, species lists, location filter) and `tests/test_session_fixtures.py::test_the_inference_default_is_at_most_two_workers`.

Notes:
- To stop each blocked download from retrying for minutes, the sandbox run used a local, uncommitted helper that makes downloads fail on the first attempt. Nothing in the repository was changed for this.
- Skipped tests (13) are platform-specific (Windows/macOS) or need optional hardware.
- Not tested yet (does not exist yet): audio streams from cameras, the Home Assistant App, MQTT entities, the Detections page, behaviour on a Raspberry Pi. These are planned in the backlog with the two test environments described in the [architecture](architecture/README.md#35-the-two-test-environments).

**GitHub CI confirmation (commit `a6d8a44`, 2026-11-21):** Tests (full suite with models downloaded, plus dependency audit) — **pass**; Lint — **pass**; Docker (x86 build + smoke test that detects birds in the example recording, and arm64 build for the Raspberry Pi) — **pass**.

**Verdict:** baseline is healthy and fully green on GitHub, including the 12 tests that could not download models in the sandbox.
