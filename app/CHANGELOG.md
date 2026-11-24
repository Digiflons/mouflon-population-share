# Changelog

## 0.7.0 — vérifications croisées : deuxième avis de Perch et observations belges (2026-11-23, MOUL-54, MOUL-55)

- **Deuxième avis (Perch).** Quand un oiseau doit être confirmé, le modèle Perch 2.0 de Google DeepMind réécoute les mêmes 3 secondes, encore en mémoire, et dit s'il entend la même espèce. Rien n'est jamais enregistré.
- **Observé localement à cette période.** Des statistiques d'observation des oiseaux en Belgique (GBIF, dix dernières années, semaine par semaine, à l'échelle du pays) sont incluses dans l'App ; rien n'est cherché en ligne.
- **La confirmation a maintenant quatre vérifications** (détection sûre, entendu à nouveau, Perch concordant, observé localement) ; un oiseau est confirmé dès que **deux** concordent. La barre de progression et le tableau de bord montrent les quatre, avec une courte explication quand l'une est passée ou négative.
- **Zones de score** (toutes réglables, libellés en français) :
  - sous 0,20 : ignoré ;
  - de 0,20 à 0,50, **vérification silencieuse** : rien n'est affiché, sauf si les statistiques belges et Perch (0,70 ou plus) sont d'accord. Le nouveau capteur « Oiseaux rattrapés par la vérification silencieuse » les compte (et ceux écartés) ;
  - de 0,50 à 0,75 : « Confirmation en cours » avec les vérifications ;
  - à partir de 0,75, oiseau courant : confirmé quand il est entendu une deuxième fois, sans Perch ;
  - oiseau nouveau, rare, ou rarement observé en Belgique à cette période : toujours vérifié.
- **Le Pi est ménagé** : Perch tourne au plus 6 fois par minute, jamais deux fois à la fois, et passe son tour quand le Pi est occupé ou manque de mémoire (les vérifications silencieuses d'abord). Une vérification passée ne bloque jamais la confirmation. Nouveau réglage pour couper Perch.
- Le mode démo montre les nouvelles vérifications.
- Perch occupe environ 0,6 Go de mémoire une fois chargé ; l'installation télécharge son modèle (413 Mo), vérifié par son empreinte.

## 0.6.1 — nettoyage interne (2026-11-23, MOUL-42, MOUL-49)

- Rien ne change pour la maison : même comportement, mêmes entités, mêmes textes.
- Code interne simplifié et code inutilisé retiré avant le partage du dépôt.

## 0.6.0 — la bibliothèque complète des gravures (2026-11-23, MOUL-42, MOUL-44)

- Toutes les gravures disponibles sont dans l'App : 163 des 215 oiseaux que l'on
  peut entendre en Belgique au fil de l'année ont maintenant leur planche ancienne
  (Naumann, Dresser, domaine public), avec sa mention de crédit. Les autres
  affichent toujours « Gravure à venir ».
- Les 33 planches qui montrent plusieurs espèces sont recadrées sur le bon oiseau,
  avec des marges généreuses ; quand les oiseaux se chevauchent ou se ressemblent
  trop, la planche entière est gardée.
- Le pack de démarrage du mode démo est remplacé par la bibliothèque complète ; la
  huppe fasciée, absente de la liste régionale, garde sa gravure pour le mode démo.
- Même papier ancien taupe et mêmes bords doux qu'en 0.5.3.
- Les chants de référence ne sont pas encore inclus.

## 0.5.3 — papier ancien, gravures entières, bords irréguliers (2026-11-22, MOUL-56, MOUL-42)

- Papier couleur taupe, comme un papier ancien, sur l'écran, ses aperçus et les
  gravures de Home Assistant. Sur l'e-ink, un fin moucheté de couleurs du panneau
  donne ce ton sans gêner la lecture des petits noms.
- Chaque gravure se fond dans le papier par un bord doux et irrégulier : plus de
  rectangle ni d'ovale visible.
- Recadrages revus pour les 18 gravures du pack de démo : marges généreuses,
  planche entière dans le doute ; plus de queue, bec ou pattes coupés. La mésange
  bleue montre maintenant la bonne espèce.
- Sur le grand écran (1200 × 1600), la gravure du dernier oiseau occupe toute la
  place ; sur une page chargée, un oiseau est réduit plutôt qu'omis.
- « Gravure à venir » est en français et sur le même papier.
- Un oiseau sans gravure est dessiné d'un trait sépia léger, sans aplat, au lieu
  d'une silhouette grise. Les petites gravures autour de la grande sont plus
  grandes et occupent mieux le cadre.
- Nouvelle vue « Écran » dans le tableau de bord, avec l'écran seul.
- Tableau de bord : une pile par oiseau (gravure jamais rognée, légende centrée).

## 0.5.2 — premières gravures en mode démo (2026-11-22, MOUL-42, MOUL-45)

- Pack de démarrage : de vraies gravures anciennes (Naumann, Dresser, domaine
  public) pour 18 des 19 oiseaux du mode démo, avec leur mention de crédit, dans
  Home Assistant et sur l'écran. Les autres oiseaux suivront avec la bibliothèque
  complète.
- Sur l'écran, chaque gravure se fond doucement dans le papier.
- Les pastilles de rareté vides ne s'affichent plus (nouveau tableau de bord).

## 0.5.1 — « Confirmation en cours » (2026-11-22, MOUL-53)

- Un oiseau en cours de confirmation affiche désormais « Confirmation en cours »
  (au lieu de « À confirmer »), avec la barre de progression, dans Home
  Assistant et sur l'écran.

## 0.5.0 — écran en collage, tout en français (2026-11-22, MOUL-56, MOUL-57)

- Tous les textes de l'App sont en français par défaut : noms des entités, états
  des sources, pastilles de rareté, étapes de confirmation, écran. Le réglage
  « Langue » reste disponible. Les identifiants des entités ne changent pas.
- Écran e-ink repensé : une planche libre, sans cadres ni grille, le dernier
  oiseau en grand au centre, très peu de texte. Le nom de la caméra n'apparaît
  plus sur l'écran.
- Nouveau réglage « Vue de l'écran » : collage (une page) ou alternate (dernier
  oiseau puis oiseaux du jour). Nouvelle entité « Écran » avec la page actuelle.
- Demande Home Assistant 2025.10 ou plus récent.

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
