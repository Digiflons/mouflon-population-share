# Changelog

## 0.7.0 — cross-checks: Perch second opinion and Belgian observations (2026-11-23, MOUL-54, MOUL-55)

- **Second opinion (Perch).** When a bird has to be confirmed, Google DeepMind's Perch 2.0 model listens again to the same 3 seconds, still in memory, and says whether it hears the same species. Nothing is ever recorded.
- **Observed locally at this time of year.** Bird observation statistics for Belgium (GBIF, last ten years, week by week, country-wide) are bundled with the App; nothing is looked up online.
- **Confirmation now has four checks** (confident detection, heard again, Perch agrees, observed locally); a bird is confirmed as soon as **two** agree. The progress bar and the dashboard show all four, with a short explanation when one is skipped or negative.
- **Score zones** (all adjustable, labels in French by default):
  - below 0.20: ignored;
  - 0.20 to 0.50, **silent check**: nothing is shown unless the Belgian statistics and Perch (0.70 or more) agree. The new sensor "Birds rescued by the silent check" counts them (and the dropped ones);
  - 0.50 to 0.75: "Confirmation in progress" with the checks;
  - from 0.75, common bird: confirmed when heard a second time, without Perch;
  - new or rare bird, or rarely observed in Belgium at this time of year: always checked.
- **The Pi is spared:** Perch runs at most 6 times a minute, never twice at once, and skips its turn when the Pi is busy or short of memory (silent checks first). A skipped check never blocks confirmation. New setting to turn Perch off.
- Demo mode shows the new checks.
- Perch takes about 0.6 GB of memory once loaded; installation downloads its model (413 MB), verified by its fingerprint.

## 0.6.1 — internal clean-up (2026-11-23, MOUL-42, MOUL-49)

- Nothing changes for the household: same behaviour, same entities, same texts.
- Internal code simplified and unused code removed before the repository was shared.

## 0.6.0 — the full engraving library (2026-11-23, MOUL-42, MOUL-44)

- All available engravings are in the App: 163 of the 215 birds that can be heard in Belgium over the year now have their antique plate (Naumann, Dresser, public domain), with its credit line. The others still show "Drawing to come" (French: "Gravure à venir").
- The 33 plates that show several species are cropped to the right bird, with generous margins; when the birds overlap or look too alike, the whole plate is kept.
- The demo mode starter pack is replaced by the full library; the hoopoe, missing from the regional list, keeps its engraving for demo mode.
- Same aged taupe paper and soft edges as in 0.5.3.
- Reference songs are not included yet.

## 0.5.3 — aged paper, whole engravings, irregular edges (2026-11-22, MOUL-56, MOUL-42)

- Taupe paper, like aged paper, on the screen, its previews and the Home Assistant engravings. On e-ink, a fine speckle of the panel's colours gives this tone without hurting the legibility of small names.
- Each engraving blends into the paper through a soft, irregular edge: no visible rectangle or oval any more.
- Crops reviewed for the 18 engravings of the demo pack: generous margins, whole plate when in doubt; no more cut-off tails, beaks or legs. The blue tit now shows the right species.
- On the large screen (1200 x 1600), the last bird's engraving fills all the space; on a busy page, a bird is shrunk rather than left out.
- "Drawing to come" is shown in French by default and on the same paper.
- A bird without an engraving is drawn with a light sepia line, without a filled shape, instead of a grey silhouette. The small engravings around the large one are bigger and fill the frame better.
- New "Screen" view in the dashboard, showing the screen alone.
- Dashboard: one stack per bird (engraving never cropped, centred caption).

## 0.5.2 — first engravings in demo mode (2026-11-22, MOUL-42, MOUL-45)

- Starter pack: real antique engravings (Naumann, Dresser, public domain) for 18 of the 19 demo-mode birds, with their credit line, in Home Assistant and on the screen. The other birds will follow with the full library.
- On the screen, each engraving blends softly into the paper.
- Empty rarity labels are no longer shown (new dashboard).

## 0.5.1 — "Confirmation in progress" (2026-11-22, MOUL-53)

- A bird being confirmed now shows "Confirmation in progress" (French: "Confirmation en cours"; it used to be "To confirm"), with the progress bar, in Home Assistant and on the screen.

## 0.5.0 — collage screen, everything in French by default (2026-11-22, MOUL-56, MOUL-57)

- All App texts are French by default: entity names, source statuses, rarity labels, confirmation steps, the screen. The "Language" setting is still available. Entity ids do not change.
- E-ink screen redesigned: a free-form plate, without frames or grid, the last bird large in the centre, very little text. The camera name no longer appears on the screen.
- New "Screen view" setting: collage (one page) or alternate (last bird, then the day's birds). New "Screen" entity with the current page.
- Requires Home Assistant 2025.10 or newer.

## 0.4.0 — birds shown right away, detection delay (2026-11-22, MOUL-53, MOUL-52)

- New and rare birds appear immediately as "provisional" with a loading bar
  (confirmation progress and steps); rarity pills and the rare-bird event only
  after confirmation; unconfirmed birds are withdrawn.
- New "Detection delay" sensor (last, median, 95th percentile, breakdown).
- Demo mode shows the confirmation flow occasionally.

## 0.3.0 — e-ink demo screen and analytics table (2026-11-22, MOUL-56, MOUL-51)

- Demo e-ink screen: "last bird" and "today's birds" views in a vintage-plate style
  (old paper, cartouche, rarity labels, open-licence fonts), as two image
  entities, refreshed slowly; size configurable (default 480x800 portrait).
- Permanent analytics table of real, confirmed garden detections (never demo or
  test), kept forever and included in Home Assistant's App backups; CSV export
  button.

## 0.2.0 — drawings, rarity and songs (2026-11-22, MOUL-42/45/47/48)

- Bird library support: each bird's 19th-century plate as a Home Assistant image
  entity (last bird + six "today" slots), with a credit line; "Drawing to come"
  when a drawing is missing. The library contents arrive in a later update.
- "Species today" now lists today's birds (most recent first, up to 30) with
  count, last heard, drawing, credit, song and rarity.
- Rarity: new / rare in the garden, unusual for Belgium now, IUCN status, with a
  confirmation rule and a separate "Rare bird" event.
- Reference songs of each species (never garden sound) installed in Home
  Assistant's media folder, playable from the dashboard through scripts.
- Demo mode fills the gallery and produces occasional demo rarities.

## 0.1.4 — slimmer documentation (2026-11-22, MOUL-49)

- The Documentation tab now only covers what a household user needs: what the App
  does, the settings, the privacy promise, the statuses, demo and test mode.
  Installation moved to the repository docs.
- The App listing no longer shows the repository address; example settings use
  generic camera names and addresses.

## 0.1.3 — demo never sleeps (2026-11-22, MOUL-50)

- Demo mode is always daytime: invented birds keep coming at any hour, in busier
  and quieter waves on a compressed 45-minute "day" that ignores the real sun.
- Real listening from the cameras still follows sunrise to sunset.

## 0.1.2 — demo mode (2026-11-21, MOUL-41)

- New "Demo mode": invented detections of common Belgian garden birds, more at
  dawn and dusk, none at night (sun entity). No audio, no model.
- Marked as fake everywhere: "Démo" source names, `demo: true` on every detection
  and event, a "Demo mode" binary sensor, a start-up log line.
- Demo data is kept in memory only and never reaches the bird log; turning demo
  off resets the last bird and the counters and removes the demo sources.
- Demo mode cannot be combined with test mode or enabled audio sources.

## 0.1.1 — fix (2026-11-21, MOUL-40)

- Test mode turns the local species filter off: the bundled test recording is
  North American, so the Belgian filter dropped every bird (0 detections on the Pi).
- New log line counting the detections the species filter drops, with their names.

## 0.1.0 — proof of concept (2026-11-21)

- Listens to RTSP sources (camera hub) or a bundled recording (test mode).
- BirdNET 2.4 on LiteRT, 3-second windows in memory, no audio kept.
- Bird log (species, confidence, source, time) and Home Assistant entities and
  "bird detected" event over MQTT.
- Battery guard with stop threshold, listening windows, optional wind/rain pause.
