# Mouflon Population

Mouflon Population écoute des caméras ou des micros extérieurs, reconnaît les chants d'oiseaux avec BirdNET et montre chaque oiseau dans Home Assistant. Tout fonctionne sur cette machine Home Assistant.

## Promesse de confidentialité

- **Aucun son n'est jamais conservé.** L'App traite le son 3 secondes à la fois, en mémoire, puis l'efface. Rien n'est enregistré ni envoyé nulle part.
- La seule chose conservée est le **journal des oiseaux** : espèce, confiance, source qui l'a entendu, et heure.
- Les voix humaines et les autres sons qui ne sont pas des oiseaux sont écartés dans l'App.
- L'App n'ouvre aucun port et ne fait que *lire* Home Assistant (niveaux de batterie, météo, position du domicile, soleil). Elle ne commande jamais vos appareils.

## Réglages (onglet Configuration)

| Réglage | Ce qu'il fait |
|---|---|
| Mode test | Rejoue un court enregistrement fourni au lieu d'écouter, pour vérifier que tout marche. Ses oiseaux sont nord-américains : le filtre des espèces locales est donc coupé en mode test (le journal le signale). Désactivez-le pour utiliser vos sources. |
| Mode démo | Montre des oiseaux **inventés** pour découvrir Home Assistant tant qu'aucun micro n'est branché (voir plus bas). Demande le mode test désactivé et toutes les sources désactivées. |
| Sources audio | Une entrée par caméra ou micro : nom, adresse du flux, identifiant (le mot de passe est masqué et reste sur cette machine), capteur de batterie de la caméra si elle est sur batterie, et *enabled*. |
| Quand écouter | **daylight** (par défaut) : du lever au coucher du soleil. **windows** : seulement pendant les plages d'écoute. **always** : jour et nuit. |
| Plages d'écoute | Seulement avec **windows**, par exemple 05:30–08:30 et 18:00–20:00. |
| Seuil d'arrêt / niveau de reprise / baisse maximale par jour | Pour les caméras sur batterie : ne réveille plus une caméra sous 40 %, reprend au-dessus de 60 %, et se met en pause si la batterie perd plus de 15 points en 24 heures. Si le niveau ne peut pas être lu, l'App n'écoute pas. |
| Seuil de publication | 0,5 par défaut : à partir de ce score, un oiseau est affiché. Augmentez-le si vous voyez de mauvais oiseaux. |
| Filtre des espèces locales | Ne garde que les oiseaux attendus chez vous à cette période de l'année. Le journal liste chaque détection écartée. |
| Capteur de vent / de pluie (facultatif) | L'écoute s'arrête par vent fort ou sous la pluie. |
| Conservation du journal | Durée de conservation du journal des oiseaux (365 jours par défaut). La rareté au jardin regarde 12 mois en arrière : gardez au moins 365. La table de statistiques permanente n'est jamais effacée par ce réglage. |
| Langue | Français par défaut pour tous les textes ; les autres langues changent les noms d'oiseaux. |
| Écran | Activé ou non, taille (480x800 par défaut, en portrait), rafraîchissement (10 minutes par défaut) et vue : **collage** (une seule page) ou **alternate** (dernier oiseau puis oiseaux du jour, à tour de rôle). |
| Rareté : jours au jardin / seuil régional / confirmation | « Rare au jardin » sous ce nombre de jours distincts en 12 mois (3) ; « inhabituel » sous cette probabilité régionale (0,10) ; une détection « sûre » à partir de cette confiance (0,75) ; délai de confirmation en minutes (15). |
| Deuxième avis (Perch) | Le modèle Perch de Google DeepMind réécoute le même instant quand un oiseau doit être confirmé (activé). Environ 0,6 Go de mémoire ; passé automatiquement si le Pi est occupé. |
| Seuil de vérification silencieuse / seuil de publication / seuil de deuxième avis | Les trois bornes des zones de score : 0,20, 0,50 et 0,75 (voir « la confirmation » ci-dessous). Valeurs de départ, à ajuster quand il y aura de vraies données du jardin. |
| Accord de Perch | Score minimal de Perch pour compter comme « d'accord » (0,70), pour le deuxième avis comme pour la vérification silencieuse. |
| Oiseau courant sûr confirmé après deux détections | Activé : un oiseau courant et sûr attend d'être entendu une deuxième fois. Désactivé : il est confirmé tout de suite. |

## Lire les états

Chaque source a un capteur d'état, `sensor.mouflon_population_<source>_status` :

| État | Signification |
|---|---|
| à l'écoute | Le son est analysé en ce moment |
| en pause : batterie faible (38 %) | Sous le seuil d'arrêt ; reprend après recharge au-dessus du niveau de reprise |
| en pause : batterie qui baisse vite | La batterie a baissé trop vite sur les dernières 24 heures |
| en pause : batterie inconnue | Le niveau de batterie n'a pas pu être lu : l'App ne réveille pas la caméra |
| en pause : vent / en pause : pluie | Pause météo |
| en dehors de la journée / en dehors des heures d'écoute | Ce n'est pas le moment d'écouter |
| hors ligne | Le flux est injoignable ; l'App réessaie toute seule |
| démo | La source est une source de démonstration (oiseaux inventés) |

Astuce : créez une automatisation qui vous prévient quand un état commence par « en pause : batterie », pour penser à recharger la caméra.

## Ce qui apparaît dans Home Assistant

Un appareil, **Mouflon Population**, avec :

| Entité | Signification |
|---|---|
| `event.mouflon_population_bird_detected` | Se déclenche pour chaque oiseau entendu : espèce, nom scientifique, confiance, source, heure. |
| `sensor.mouflon_population_last_bird` | Le dernier oiseau entendu, avec ses détails en attributs. |
| `sensor.mouflon_population_species_today` / `..._detections_today` | Les compteurs du jour. |
| `binary_sensor.mouflon_population_<source>_listening` | Allumé quand la source est écoutée. |
| `binary_sensor.mouflon_population_demo_mode` | **Allumé pendant le mode démo : les oiseaux montrés sont inventés.** |
| `image.mouflon_population_screen` | La page actuelle de l'écran e-ink. |

## Gravures, rareté et chants

- **Gravures :** chaque oiseau est montré avec une planche coloriée à la main du XIXe siècle (domaine public), avec sa mention de crédit. Les gravures sont présentées sur un papier ancien couleur taupe, avec un bord irrégulier qui se fond dans le papier. Les oiseaux sans gravure affichent « Gravure à venir ».
- **Pastilles de rareté :**
  - « Nouveau pour le jardin » : jamais entendu ici ;
  - « Rare au jardin » : entendu moins de 3 jours sur les 12 derniers mois ;
  - « Inhabituel en Belgique » : la saison et le lieu le rendent inattendu ;
  - le statut de conservation mondial (par exemple « Quasi menacé »).

  Un oiseau rare ne compte qu'une fois confirmé (voir ci-dessous) ; d'ici là il est marqué « Confirmation en cours ». Les oiseaux rares confirmés déclenchent l'événement `event.mouflon_population_rare_bird`, utilisable pour une notification sur téléphone.
- **Chants :** un bouton ou une automatisation peut faire écouter un **enregistrement de référence de l'espèce** (xeno-canto, crédité) ; toucher une gravure ouvre sa fiche. Ce n'est jamais un son enregistré dans votre jardin.

## Oiseaux incertains, nouveaux et rares : la confirmation

Selon le score de BirdNET :

| Score | Ce qui se passe |
|---|---|
| Sous 0,20 | Ignoré. |
| 0,20 à 0,50 : **vérification silencieuse** | Rien n'est affiché. L'App vérifie en arrière-plan que l'espèce est couramment observée en Belgique cette semaine et demande l'avis de Perch. L'oiseau n'est affiché que si les deux sont d'accord (Perch à 0,70 ou plus) ; il passe alors en « Confirmation en cours ». Sinon il est écarté. Le capteur « Oiseaux rattrapés par la vérification silencieuse » compte les oiseaux rattrapés (et, en attribut, ceux écartés). |
| 0,50 à 0,75 : **incertain** | Affiché tout de suite en « Confirmation en cours », avec les vérifications. |
| 0,75 et plus, oiseau courant en Belgique cette semaine, ni nouveau ni rare au jardin | Affiché tout de suite, confirmé quand il est entendu une deuxième fois (sans Perch, pour ménager le Pi). |
| Oiseau nouveau ou rare au jardin, inhabituel, menacé, ou rarement observé en Belgique cette semaine | Toujours vérifié, quel que soit le score. |

Pendant la « Confirmation en cours », une barre de progression et quatre vérifications sont affichées :

1. **Détection sûre** : BirdNET donne au moins 0,75.
2. **Entendu à nouveau** dans les 15 minutes.
3. **Deuxième avis (Perch) concordant** : le modèle Perch de Google DeepMind réécoute les mêmes 3 secondes, encore en mémoire, et reconnaît le même oiseau.
4. **Observé localement à cette période** : selon les statistiques d'observation belges de GBIF, incluses dans l'App (rien n'est cherché en ligne).

L'oiseau est **confirmé dès que deux vérifications concordent** (trois pour un oiseau rattrapé par la vérification silencieuse). Alors seulement apparaissent ses pastilles de rareté et la notification d'oiseau rare. Une vérification qui ne peut pas se faire (Pi occupé, par exemple) est marquée « passée » et ne bloque jamais. S'il n'est pas confirmé à temps, il affiche « Non confirmé » et quitte la liste du jour. Il n'y a rien à appuyer.

Tous ces seuils sont réglables. Le score de BirdNET n'est pas une vraie probabilité : ce sont des valeurs de départ, à ajuster après quelques semaines de vraies données du jardin.

## Écran e-ink et export des données

- **Écran :** une composition libre façon planche d'histoire naturelle ancienne, le dernier oiseau en grand au centre et les oiseaux du jour autour, avec très peu de texte (nom, nom scientifique, heure). Le nom de la caméra n'y figure jamais. L'écran change lentement (toutes les 10 minutes au plus). Il est prévu pour un futur cadre e-ink couleur ; en attendant, il s'affiche dans Home Assistant (entités « Écran »).
- **Statistiques :** chaque oiseau confirmé est aussi gardé, définitivement, dans une table séparée pour les statistiques de saison (jamais les oiseaux de démo ou de test). Appuyez sur **Exporter les statistiques (CSV)** pour écrire un fichier tableur dans le dossier média (`mouflon_population/exports`).

## Mode démo (oiseaux inventés)

- Invente des détections d'oiseaux de jardin courants. Il ne fait jamais nuit en mode démo : les oiseaux arrivent à toute heure, par vagues plus ou moins actives. Aucun son n'est utilisé et aucun modèle BirdNET ne tourne.
- **Clairement faux partout :** les sources s'appellent « Démo … », chaque détection porte `demo: true`, le capteur Mode démo est allumé et le journal indique « DEMO MODE ON ».
- **Jamais mélangé aux vraies données :** les oiseaux de démo ne sont jamais écrits dans le journal des oiseaux.
- **Pour l'arrêter** (puis redémarrer) : le dernier oiseau et les compteurs reviennent au vrai journal, et les sources « Démo » disparaissent. Les anciennes valeurs de démo dans l'historique de Home Assistant restent reconnaissables à `demo: true`.

## Mode test

Rejoue un enregistrement fourni d'une minute pour vérifier toute la chaîne sans réveiller de caméra. Les oiseaux doivent apparaître en moins d'une minute.
