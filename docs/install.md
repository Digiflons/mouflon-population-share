# Installing and setting up Mouflon Population

For whoever installs the App. The App's own Documentation tab in Home Assistant (`app/DOCS.md`) only covers what a household user needs; everything technical is here.

## 1. Read access to the private repository

The repository is private, so Home Assistant needs a **read-only GitHub token that the owner creates and pastes personally**. Never share it in a chat, an email or a file.

1. On GitHub: your picture → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token.
   - **Resource owner:** the organisation that owns the repository
   - **Repository access:** *Only select repositories* → this repository only
   - **Permissions:** Repository permissions → **Contents: Read-only** (GitHub adds *Metadata: Read-only*). Everything else *No access*.
   - **Expiration:** set an expiry (for example 90 days) and a reminder to renew it. When it expires, the App keeps running but Home Assistant can no longer fetch updates.
2. In Home Assistant: Settings → Apps → App store → ⋮ → Repositories, and paste:

   `https://x-access-token:<TOKEN>@github.com/<OWNER>/<REPOSITORY>#staging`

   Keep the `x-access-token:` part: the shorter form without it fails with "could not read Username". `#staging` keeps Home Assistant on the staging branch during the proof of concept. `<OWNER>/<REPOSITORY>` is the repository's address on GitHub; `<TOKEN>` is a placeholder; never write a real token anywhere.
3. Install **Mouflon Population** from the App store. Home Assistant builds it on the machine itself (several minutes; the build downloads about 0.6 GB of model files, including the 413 MB Perch model, each checked against its fingerprint); nothing comes from an image registry.

If the token ever leaks, delete it on GitHub and create a new one. It only allows reading this repository's code, which contains no secrets.

## 2. MQTT broker

Install and start the **Mosquitto broker** App, and accept the MQTT integration Home Assistant then offers. Mouflon Population receives its MQTT connection details from the Supervisor automatically; no MQTT login is typed into it.

## 3. Camera streams

For battery cameras behind a hub:

1. In the hub's own app, turn on **RTSP**.
2. Create a **separate user with viewing rights only**, with its own password.
3. Find the RTSP address of each camera in the hub's documentation (many hubs use a pattern such as `rtsp://<hub address>:554/<stream path>`; a low-bandwidth sub-stream carries the same sound).
4. In the App's Configuration tab, per source: **url** without the login, **username** and **password** of the viewing-only user (typed by the owner; masked and stored by Home Assistant), the camera's **battery sensor**, and **enabled**.

Start with **test mode** on to check the chain, or **demo mode** to preview the dashboard.

## 4. The "Birds" dashboard

Reference copies: `docs/home-assistant/birds-dashboard.yaml` (dashboard) and `docs/home-assistant/outdoor-birds-section.yaml` (a section for another view).

1. Settings → Dashboards → **Add dashboard** → "New dashboard from scratch", title **Birds**, URL **birds-dashboard**.
2. Open it → ⋮ → **Edit dashboard** → ⋮ → **Raw configuration editor**, paste `birds-dashboard.yaml`, save.
3. For another view: Edit → add a section → **Edit in YAML**, paste `outdoor-birds-section.yaml`.

The **Listening** section holds demo-mode cards (shown only while demo mode is on). When real sources are configured, uncomment the per-source status/listening cards at the end of that section and adjust the entity names to your source names.

## 5. Songs, rare-bird notification and the Gallery

- **Songs:** create the two scripts in `docs/home-assistant/scripts.yaml` (Settings → Automations & scenes → Scripts → Edit in YAML) and set the speaker (`media_player.…`) that should play them. Since 0.5.3 tapping a drawing opens its details instead; call the scripts from a button or an automation. Playing in the browser itself would need an extra card (for example browser_mod); ask the owner first.
- **Rare-bird notification:** import `docs/home-assistant/automation-rare-bird.yaml` and set your phone's notify action.
- **Écran view:** `birds-dashboard.yaml` also has a second view, **Écran** (`/birds-dashboard/ecran`, one column), showing only the e-ink demo screen image; open it on a tablet to stand in for the frame.
- **Gallery:** it is part of `birds-dashboard.yaml`: one vertical stack per bird (a picture-entity with no `aspect_ratio`, so the plate is never cropped, then a centred legend). Its rarity chips need Mushroom (HACS). A swipe/carousel card can replace the six static tiles later, after the owner approves installing one (see the architecture, section 7).

## 6. Building the bird library (maintainers)

- The "Bird illustrations" workflow builds the drawings, songs and IUCN data on GitHub's servers. Its `save-for-review` job saves the result on the separate `library-build` branch (owner's decision, 2026-11-22). It never writes to `staging` or `main`.
- Review `build/contact-sheet.html` and `build/coverage.md` on that branch. The coverage report separates species with **no plate on Commons** (missing) from plates that **failed, retry later** (Wikimedia was busy) and species **not attempted** because the run stopped 15 minutes before its time limit to save its work. Running the full build again fetches only what is not there yet (plates are kept in the workflow cache). After the owner approves, install on `staging` with `python tools/illustrations/install.py <path to build/> --extra <path to demo-pack/>`. The full build replaces everything installed before; `--extra` only fills species the full build has no drawing for (the demo mode's hoopoe). A plate showing several species is installed only once `tools/illustrations/crops.json` has a reviewed box for that exact Commons file (or `"whole"`); push a change to `crops.json` with `tools/illustrations/STEP` set to `all` to rebuild with the new boxes, then install the saved build.
- Optional repository settings, set by the owner only if wanted: a `XENO_CANTO_API_KEY` secret (if xeno-canto requires a key), and a `WIKIMEDIA_CONTACT` **secret** (a contact that Wikimedia asks automated downloaders to include; without it, downloads are more rate-limited). It must be a secret, not a variable: GitHub hides secrets in the run logs but shows variables. The workflow never prints it. Both are read from the repository running the workflow: a fork or copy sets **its own** `WIKIMEDIA_CONTACT` (a contact address of whoever runs the build) and, if wanted, its own `XENO_CANTO_API_KEY`, under Settings → Secrets and variables → Actions. Without them the workflow still runs, with a generic User-Agent and no songs.

## 6b. Delay benchmark on the real hardware (MOUL-52, with MOUL-12)

1. Run the App on the target Raspberry Pi with the real cameras and real listening.
2. Watch `sensor.mouflon_population_detection_delay` over a day of common birds. Its median and 95th percentile cover inference, publishing and Home Assistant.
3. Measure the stream delay once by making a sharp sound (a clap) in front of a camera, and noting the time it appears in the App's log ("Detection delay …").
4. Record the results in the work file. The estimate is about 3–6 s for a common bird, to be confirmed.

## 7. Backups and restore (bird log and analytics table)

- The bird log and the permanent analytics table live in the App's data folder. Home Assistant's backups include them whenever the App is part of the backup: a full backup, or a partial backup with "Mouflon Population" ticked.
- **Restore:**
  1. Settings → System → Backups, pick a backup, then Restore.
  2. Select the Mouflon Population App (or a full restore).
  3. The App restarts with the data as of that backup.
  Detections made after the backup are not in it.
- **CSV export:** press "Export bird analytics (CSV)" on the Mouflon Population device. The file appears in the media folder under `mouflon_population/exports/`. It is reachable with a file-access App (for example the Samba share "media" or a file editor configured for /media). The "Last analytics export" sensor shows the file name and the number of rows.

## 8. E-ink demo screen

- Settings: `screen_enabled`, `screen_size` (default 480x800, portrait), `screen_refresh_minutes` (default 10), `screen_view` (`collage` by default, or `alternate`).
- Home Assistant shows what the frame would show as `image.mouflon_population_screen`, plus the two single pages `image.mouflon_population_screen_last_bird` and `image.mouflon_population_screen_today`. The documented dashboard has an "Écran" section with the frame, which can be shown full-width on a tablet to simulate it.
- **Preview in the repository:** `docs/screen-preview/preview.html` opens by double-click (self-contained, no server), with buttons to switch view, size and normal or e-ink rendering. The PNGs sit next to it. They are regenerated in the same commit whenever the layout changes.
- Preview from the command line: `PYTHONPATH=app/src python -m mouflon_population.screen --input app/samples/detections.json --output docs/screen-preview` (add `--library <folder>` to use real drawings, `--sizes 480x800` to change the sizes, `--watch` to regenerate on every change).

### 8.1 Live screen preview in VS Code, on a Mac (one-time setup, MOUL-57)

Goal: the e-ink screen shows in a panel next to the code and updates by itself each time the layout changes, including when Claude Code makes the change.

**Once only:**

1. **Install Python.** Go to python.org → Downloads → macOS, download the latest "macOS 64-bit universal2 installer" (Python 3.13), open it and click through to the end. The Python already on a Mac is too old for this.
2. **Open the project in VS Code.** File → Open Folder… → choose the `mouflon-population` folder.
3. **Install the recommended extensions.** VS Code shows a message "Do you want to install the recommended extensions?": click **Install**. If the message does not appear: open the Extensions panel (the four squares icon on the left), type `@recommended`, and install **Live Preview** (publisher: Microsoft).
4. **Allow the project's tasks.** If VS Code asks whether you trust the authors of this folder, answer **Yes, I trust the authors**: the task below needs it.

**Every time you want the preview:**

1. Menu **Terminal → Run Task…** and choose **Aperçu écran e-ink** (French for "e-ink screen preview"; the task names are French UI text).
2. The first time only, a terminal panel prints "Première fois : création de l'environnement Python…" (first time: creating the Python environment) and "Installation de Pillow…" (installing Pillow). This takes about a minute.
3. When the terminal prints **"Aperçu prêt."** (preview ready), the preview opens in a side panel. If it does not, open `docs/screen-preview/preview.html` in the file list, then click the preview icon at the top right of the editor (or right-click the file → "Show Preview").
4. Use the buttons at the top of the page: **Vue** (View: last bird, day's birds, single collage), **Taille** (Size: 7.3 or 13.3 inches) and **Rendu** (Rendering: screen or e-ink). Your choice is remembered after each refresh.
5. Change the layout yourself, or ask Claude Code to. After each saved change the terminal prints "Rendu en cours…" (rendering) then "Aperçu prêt." (preview ready), and the panel reloads by itself (a few seconds; both sizes are drawn).
6. To stop: click in the terminal panel and press **Ctrl+C**, or close that terminal.

**If something goes wrong:**

- "Python 3.11 ou plus récent est introuvable" (Python 3.11 or newer not found): do step 1 of the one-time setup, then close and reopen VS Code.
- "Erreur de rendu." (rendering error): the last change broke the drawing; the terminal shows why above that line. The previous preview stays in place until the next good change.
- To start again from scratch, delete the `.venv-screen` folder in the project and run the task again.

**Safety:** the task works only on this computer. On first run it downloads one library, Pillow, at the exact version and checksum written in `tools/screen_preview/requirements.lock`; after that it makes no network connection. Live Preview shows the page from a local server reachable only from this Mac (address 127.0.0.1). Nothing is sent anywhere and nothing is installed on the Raspberry Pi.

## 9. Security notes

- Threat model and findings: `docs/security.md`.
- The App opens no port, runs as an unprivileged user, reads Home Assistant only through the Supervisor-scoped token, and keeps no audio.
