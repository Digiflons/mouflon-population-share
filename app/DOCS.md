# Mouflon Population

Mouflon Population listens to outdoor cameras or microphones, recognises bird songs with BirdNET and shows each bird in Home Assistant. Everything runs on this Home Assistant machine.

The App's screens and entity names are French by default; set **Language** to English to see them in English. This page gives the English wording and, where useful, the French text in brackets.

## Privacy promise

- **No sound is ever kept.** The App processes sound 3 seconds at a time, in memory, then deletes it. Nothing is recorded or sent anywhere.
- The only thing kept is the **bird log**: species, confidence, the source that heard it, and the time.
- Human voices and other sounds that are not birds are discarded inside the App.
- The App opens no port and only *reads* from Home Assistant (battery levels, weather, home location, sun). It never controls your devices.

## Settings (Configuration tab)

| Setting | What it does |
|---|---|
| Test mode | Replays a short bundled recording instead of listening, to check that everything works. Its birds are North American, so the local species filter is switched off in test mode (the log says so). Turn it off to use your sources. |
| Demo mode | Shows **invented** birds so you can explore Home Assistant while no microphone is connected (see below). Needs test mode off and all sources disabled. |
| Audio sources | One entry per camera or microphone: name, stream address, user name (the password is hidden and stays on this machine), the camera's battery sensor if it runs on a battery, and *enabled*. |
| When to listen | **daylight** (default): from sunrise to sunset. **windows**: only during the listening windows. **always**: day and night. |
| Listening windows | Only with **windows**, for example 05:30-08:30 and 18:00-20:00. |
| Stop threshold / resume level / maximum drop per day | For battery cameras: a camera below 40 % is no longer woken up, listening resumes above 60 %, and it pauses if the battery loses more than 15 points in 24 hours. If the level cannot be read, the App does not listen. |
| Publication threshold | 0.5 by default: from this score, a bird is shown. Raise it if you see wrong birds. |
| Local species filter | Keeps only the birds expected at your place at this time of year. The log lists every detection it drops. |
| Wind / rain sensor (optional) | Listening stops in strong wind or rain. |
| Log retention | How long the bird log is kept (365 days by default). Garden rarity looks back 12 months, so keep at least 365. The permanent statistics table is never deleted by this setting. |
| Language | French by default for all texts; English shows the texts in English; other languages change the bird names. |
| Screen | On or off, size (480x800 by default, portrait), refresh (every 10 minutes by default) and view: **collage** (a single page) or **alternate** (last bird, then the day's birds, in turn). |
| Rarity: days in the garden / regional threshold / confirmation | "Rare in the garden" below this number of distinct days in 12 months (3); "unusual" below this regional probability (0.10); a detection is "confident" from this score (0.75); confirmation delay in minutes (15). |
| Second opinion (Perch) | Google DeepMind's Perch model listens again to the same moment when a bird has to be confirmed (on). About 0.6 GB of memory; skipped automatically when the Pi is busy. |
| Silent-check threshold / publication threshold / second-opinion threshold | The three limits of the score zones: 0.20, 0.50 and 0.75 (see "Confirmation" below). Starting values, to adjust once there is real garden data. |
| Perch agreement | Minimum Perch score to count as "agrees" (0.70), for the second opinion and for the silent check. |
| Common confident bird confirmed after two detections | On: a common, confident bird waits to be heard a second time. Off: it is confirmed straight away. |

## Reading the statuses

Each source has a status sensor, `sensor.mouflon_population_<source>_status`. With the French default the status text is French; the English equivalent is given here.

| Status (French) | Meaning |
|---|---|
| listening (`à l'écoute`) | Sound is being analysed right now |
| paused: battery low (`en pause : batterie faible`, for example 38 %) | Below the stop threshold; resumes after recharging above the resume level |
| paused: battery dropping fast (`en pause : batterie qui baisse vite`) | The battery dropped too fast over the last 24 hours |
| paused: battery unknown (`en pause : batterie inconnue`) | The battery level could not be read: the App does not wake the camera |
| paused: wind / paused: rain (`en pause : vent` / `en pause : pluie`) | Weather pause |
| outside daylight / outside listening hours (`en dehors de la journée` / `en dehors des heures d'écoute`) | Not the time to listen |
| offline (`hors ligne`) | The stream cannot be reached; the App retries by itself |
| demo (`démo`) | The source is a demonstration source (invented birds) |

Tip: create an automation that notifies you when a status starts with "paused: battery" (`en pause : batterie`), as a reminder to recharge the camera.

## What appears in Home Assistant

One device, **Mouflon Population**, with:

| Entity | Meaning |
|---|---|
| `event.mouflon_population_bird_detected` | Fires for every bird heard: species, scientific name, confidence, source, time. |
| `sensor.mouflon_population_last_bird` | The last bird heard, with its details as attributes. |
| `sensor.mouflon_population_species_today` / `..._detections_today` | The day's counters. |
| `binary_sensor.mouflon_population_<source>_listening` | On while the source is being listened to. |
| `binary_sensor.mouflon_population_demo_mode` | **On during demo mode: the birds shown are invented.** |
| `image.mouflon_population_screen` | The current page of the e-ink screen. |

## Engravings, rarity and songs

- **Engravings:** each bird is shown with a hand-coloured 19th-century plate (public domain), with its credit line. Plates sit on aged taupe paper, with an irregular edge that blends into the paper. Birds without a plate show "Drawing to come" (`Gravure à venir`).
- **Rarity labels:**
  - "New for the garden" (`Nouveau pour le jardin`): never heard here;
  - "Rare in the garden" (`Rare au jardin`): heard on fewer than 3 days in the last 12 months;
  - "Unusual for Belgium now" (`Inhabituel en Belgique`): the season and place make it unexpected;
  - the world conservation status (for example "Near threatened", `Quasi menacé`).

  A rare bird only counts once confirmed (see below); until then it is marked "Confirmation in progress" (`Confirmation en cours`). Confirmed rare birds fire the `event.mouflon_population_rare_bird` event, which you can use for a phone notification.
- **Songs:** a button or an automation can play a **reference recording of the species** (xeno-canto, credited); touching a plate opens its page. This is never sound recorded in your garden.

## Uncertain, new and rare birds: confirmation

Depending on BirdNET's score:

| Score | What happens |
|---|---|
| Below 0.20 | Ignored. |
| 0.20 to 0.50: **silent check** | Nothing is shown. In the background the App checks that the species is commonly seen in Belgium this week and asks Perch for its opinion. The bird is shown only if both agree (Perch at 0.70 or more); it then goes to "Confirmation in progress". Otherwise it is dropped. The sensor "Birds rescued by the silent check" (`Oiseaux rattrapés par la vérification silencieuse`) counts the rescued birds (and, as an attribute, the dropped ones). |
| 0.50 to 0.75: **uncertain** | Shown straight away as "Confirmation in progress", with the checks. |
| 0.75 and above, a bird common in Belgium this week, neither new nor rare in the garden | Shown straight away, confirmed when heard a second time (without Perch, to spare the Pi). |
| A bird new or rare in the garden, unusual, threatened, or rarely seen in Belgium this week | Always checked, whatever the score. |

During "Confirmation in progress", a progress bar and four checks are shown:

1. **Confident detection:** BirdNET gives at least 0.75.
2. **Heard again** within 15 minutes.
3. **Second opinion (Perch) agrees:** Google DeepMind's Perch model listens again to the same 3 seconds, still in memory, and recognises the same bird.
4. **Observed locally at this time of year:** based on Belgian GBIF observation statistics bundled with the App (nothing is looked up online).

The bird is **confirmed as soon as two checks agree** (three for a bird rescued by the silent check). Only then do its rarity labels and the rare-bird notification appear. A check that cannot be done (Pi busy, for example) is marked "skipped" and never blocks. If the bird is not confirmed in time, it shows "Not confirmed" (`Non confirmé`) and leaves the day's list. There is nothing to press.

All these thresholds can be changed. BirdNET's score is not a true probability: these are starting values, to adjust after a few weeks of real garden data.

## E-ink screen and data export

- **Screen:** a free-form layout in the style of an old natural-history plate, the last bird large in the centre and the day's birds around it, with very little text (name, scientific name, time). The camera name never appears on it. The screen changes slowly (every 10 minutes at most). It is meant for a future colour e-ink frame; until then it is shown in Home Assistant ("Screen" entities, `Écran`).
- **Statistics:** each confirmed bird is also kept, permanently, in a separate table for season statistics (never demo or test birds). Press **Export statistics (CSV)** (`Exporter les statistiques (CSV)`) to write a spreadsheet file in the media folder (`mouflon_population/exports`).

## Demo mode (invented birds)

- Invents detections of common garden birds. It is never night in demo mode: birds arrive at any hour, in busier and quieter waves. No sound is used and no BirdNET model runs.
- **Clearly fake everywhere:** sources are named "Démo ..." (`Démo` is French for "demo"), every detection carries `demo: true`, the Demo mode sensor is on and the log says "DEMO MODE ON".
- **Never mixed with real data:** demo birds are never written to the bird log.
- **To stop it** (then restart): the last bird and the counters go back to the real log, and the "Démo" sources disappear. Old demo values in Home Assistant's history remain recognisable by `demo: true`.

## Test mode

Replays a bundled one-minute recording to check the whole chain without waking a camera. Birds should appear in under a minute.
