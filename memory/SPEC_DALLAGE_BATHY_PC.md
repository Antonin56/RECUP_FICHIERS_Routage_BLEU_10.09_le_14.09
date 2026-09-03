# SPÉCIFICATION — Script PC (Windows) de dallage bathymétrique SHOM

Version 1.0 — 03/09/2026 — Rédigé pour l'armateur SignalMar.
Objet : script Python **autonome** (PC Windows) qui télécharge les MNT SHOM,
les convertit et les découpe en **dalles de navigation compressées NumPy
(.npy)** de 10 ou 20 km, avec un **index JSON** permettant au moteur de
routage de ne charger que le nécessaire.
AUCUN CODE dans ce document — uniquement la spécification.

---

## 1. Périmètre et objectif

- Secteur prioritaire : **Golfe du Morbihan → Belle-Île** (couvert à 100 %
  par le produit TANDEM Morbihan 20 m).
- Extension possible : toute la façade Atlantique via HOMONIM 100 m, et
  toute côte bretonne fine via Litto3D (chapitre 9).
- Sortie : répertoire de dalles `.npy` float32 + 1 fichier `index.json`.
- Convention UNIQUE en sortie (identique à SignalMar) :
  **profondeur en mètres sous le zéro hydrographique (ZH/PBMA), positive
  vers le bas ; NaN = terre / hors donnée = JAMAIS navigable.**

## 2. Prérequis Windows

- Python 3.11+ (installeur python.org, cocher « Add to PATH »).
- Bibliothèques (toutes disponibles en wheels binaires Windows, aucune
  compilation ni GDAL système requis) :
  - `numpy` (grilles, .npy),
  - `rasterio` (lecture Arc/Info ASCII .asc, fenêtrage, géoréférencement),
  - `py7zr` (extraction des archives .7z du SHOM),
  - `requests` ou `httpx` (téléchargement HTTP avec reprise).
- Espace disque : prévoir **3 Go temporaires** (archive + .asc décompressé)
  pour le TANDEM ; **6 Go** si HOMONIM ajouté. Sortie finale : < 100 Mo.
- Aucune clé, aucun compte : données SHOM sous **Licence Ouverte**
  (mention obligatoire : « Bathymétrie © SHOM — non utilisable pour la
  navigation officielle »).

## 3. Connexion SHOM — URLs EXACTES (vérifiées 03/09/2026, HTTP 200)

Service de téléchargement INSPIRE, HTTPS simple, sans authentification.

### 3.1 Produit principal : MNT côtier Morbihan TANDEM 20 m (PBMA)
- Groupe : `MNT_COTIER_MORBIHAN_TANDEM_20m_PBMA_4326_PACK_DL`
- Paquet : `MNT_COTIER_MORBIHAN_TANDEM_PBMA`
- URL directe (105 627 341 octets ≈ 105 Mo) :
```
https://services.data.shom.fr/INSPIRE/telechargement/prepackageGroup/MNT_COTIER_MORBIHAN_TANDEM_20m_PBMA_4326_PACK_DL/prepackage/MNT_COTIER_MORBIHAN_TANDEM_PBMA/file/MNT_COTIER_MORBIHAN_TANDEM_PBMA.7z
```
- Contenu de l'archive :
  `MNT_COTIER_MORBIHAN_TANDEM_PBMA/DONNEES/MNT_COTIER_MORBIHAN_TANDEM_20m_WGS84_PBMA_ZNEG.asc`
- Emprise : lng −3.3334 → −2.367, lat 47.20 → 47.725 (Golfe, Vilaine,
  Quiberon, Houat, Hoëdic, **Belle-Île incluse**).
- Grille : 2626 lignes × 4834 colonnes, pas 0.0002° (≈ 20 m), lignes du
  NORD vers le SUD.
- Variante NM (niveau moyen) au même endroit, paquet
  `MNT_COTIER_MORBIHAN_TANDEM_NM` — NE PAS l'utiliser (on veut PBMA =
  basses mers, conservateur).

### 3.2 Produit large : MNT façade Atlantique HOMONIM 100 m (PBMA)
- Groupe : `MNT_ATL100m_HOMONIM_PBMA_4326_PACK_DL`
- Paquet : `MNT_FACADE_ATLANTIQUE_HOMONIM_PBMA`
- URL directe (463 729 279 octets ≈ 464 Mo → .asc d'~1 Go) :
```
https://services.data.shom.fr/INSPIRE/telechargement/prepackageGroup/MNT_ATL100m_HOMONIM_PBMA_4326_PACK_DL/prepackage/MNT_FACADE_ATLANTIQUE_HOMONIM_PBMA/file/MNT_FACADE_ATLANTIQUE_HOMONIM_PBMA.7z
```
- Contenu : `.../DONNEES/MNT_ATL100m_HOMONIM_WGS84_PBMA_ZNEG.asc`,
  pas 0.001° (≈ 100 m). À CROPPER à la fenêtre voulue à la lecture
  (rasterio fenêtré) — ne jamais charger le fichier entier en RAM.

### 3.3 Découverte du catalogue (pour d'autres zones)
- GetCapabilities global :
  `https://services.data.shom.fr/INSPIRE/telechargement/prepackageGroup?request=GetCapabilities`
- Listing JSON d'un groupe (renvoie `prepackageResources[].prepackageName`) :
  `https://services.data.shom.fr/INSPIRE/telechargement/prepackageGroup/{GROUPE}`
- Les fiches produit sont aussi indexées sur data.gouv.fr et data.shom.fr
  (recherche « MNT TANDEM » / « HOMONIM »).

### 3.4 Robustesse réseau (OBLIGATOIRE)
- Le SHOM **coupe les gros transferts** en cours de route. Le serveur
  supporte `Accept-Ranges: bytes` (vérifié) : implémenter la **reprise**
  avec l'en-tête `Range: bytes=N-` sur un fichier `.part`, boucle de
  tentatives (25 max, pause 2-5 s), contrôle final de la taille contre le
  `Content-Length` initial.
- Vérifier le `Content-Type: application/x-7z-compressed` (une page HTML
  d'erreur = mauvais nom de paquet).

## 4. Format d'entrée SHOM (.asc)

- **Arc/Info ASCII Grid** : en-tête texte (`ncols`, `nrows`, `xllcorner`,
  `yllcorner`, `cellsize`, `nodata_value`) puis les valeurs, ligne 1 = bord
  NORD. Lecture via rasterio en float32.
- Convention SHOM « **ZNEG PBMA** » : la valeur est une **ALTITUDE** par
  rapport au zéro hydro (PBMA) → **négative sous l'eau**.
- `nodata` = float géant (~±1e30), parfois arrondi → double garde-fou :
  remplacer le nodata déclaré PUIS toute valeur |v| > 1e30 par NaN.

## 5. Transformation (pipeline, dans l'ordre)

1. Télécharger le `.7z` (reprise Range, §3.4).
2. Extraire le `.asc` (py7zr) dans un répertoire de travail.
3. Ouvrir avec rasterio ; lire en float32 (fenêtré pour HOMONIM).
4. nodata → NaN ; garde-fou |v| > 1e30 → NaN.
5. **Inverser le signe** : profondeur = −altitude (ZNEG → profondeur
   positive sous ZH).
6. Découper en dalles (§6) et écrire `.npy` + `index.json` (§7).
7. Supprimer les fichiers temporaires (.7z, .asc) — option `--keep-sources`.

## 6. Dallage 10 / 20 km — carroyage recommandé

**Choix recommandé : carroyage en DEGRÉS, aligné sur la grille SHOM**
(le .asc est déjà en WGS84 au pas 0.0002° — aucune reprojection, aucun
rééchantillonnage, donc AUCUNE perte ni déformation de la donnée) :

- **Dalle = 0.1° × 0.1°** → 500 × 500 cellules au pas 0.0002°
  ≈ **11,1 km N-S × 7,5 km E-O** (à 47,5° N) ≈ ta cible 10 km.
  Poids : 500×500×4 octets = **1,0 Mo** par dalle (NaN compris).
- Variante 20 km : **0.2° × 0.2°** → 1000 × 1000 cellules = 4,0 Mo/dalle.
- Indexation ENTIÈRE et déterministe :
  `ix = floor(lng / 0.1)` (négatif à l'ouest de Greenwich),
  `iy = floor(lat / 0.1)`.
  Nom de fichier : `tile_20m_{iy}_{ix}.npy`
  (ex. Port-Navalo lat 47.54, lng −2.92 → `tile_20m_475_-30.npy`).
- Origine de chaque dalle : coin NORD-OUEST exact
  `lng0 = ix·0.1`, `lat0 = (iy+1)·0.1`, lignes nord → sud (dy = −0.0002).
- Les dalles **partiellement couvertes** par le produit sont complétées en
  NaN (jamais tronquées : toutes les dalles font exactement 500×500).
- Les dalles **entièrement NaN** (pleine terre ou hors produit) ne sont
  PAS écrites — elles sont simplement absentes de l'index.
- **Halo/recouvrement : AUCUN.** Le moteur charge la dalle du point + les
  8 voisines quand la fenêtre de calcul chevauche un bord (plus simple et
  sans duplication de données). Si tu préfères l'autre école : halo d'1
  cellule dupliquée par bord — à décider, mais pas les deux.
- Volumétrie secteur Golfe → Belle-Île : emprise TANDEM ≈ 0.97° × 0.53°
  → **~55 dalles de 0.1°**, ≈ 50-55 Mo au total (avant compression NPZ
  éventuelle, §7.3).

Pourquoi PAS le Lambert-93 kilométrique (comme les dalles Litto3D) : il
imposerait une reprojection/rééchantillonnage du .asc WGS84 (perte,
interpolation, risque d'adoucir une roche). Le carroyage degrés colle à la
grille native — c'est le choix SignalMar.

## 7. Format de sortie

### 7.1 Dalle `.npy`
- `numpy.save`, tableau **float32** de forme (nrows, ncols) fixe
  (500×500 ou 1000×1000), ligne 0 = bord NORD.
- Valeur = profondeur (m) sous ZH, positive vers le bas ; **NaN = terre /
  île / hors donnée = interdit**. Aucune autre sentinelle (pas de −9999).
- Lecture côté moteur : `numpy.load(..., mmap_mode="r")` (memmap, jamais
  chargé entier en RAM).

### 7.2 Index `index.json` (UN SEUL fichier à la racine des dalles)
Champs obligatoires :
- `version` : entier (1).
- `convention` : chaîne fixe
  `"depth_m_below_ZH_positive_down;NaN=land_or_nodata"`.
- `crs` : `"EPSG:4326"`.
- `license` : `"Licence Ouverte — Bathymétrie © SHOM (non officiel navigation)"`.
- `tile_deg` : 0.1 (ou 0.2).
- `cell_deg` : 0.0002 (pas de la grille ; 0.001 pour une couche HOMONIM).
- `tile_size` : 500 (cellules par côté ; 1000 en 20 km).
- `row_order` : `"north_to_south"`.
- `layers` : liste ordonnée de la plus FINE à la plus GROSSIÈRE, chaque
  couche = objet :
  - `name` : `"tandem_morbihan_20m"`,
  - `product` : `"MNT_COTIER_MORBIHAN_TANDEM_20m_WGS84_PBMA_ZNEG"`,
  - `source_url` : l'URL directe du §3,
  - `downloaded_at` : ISO-8601 UTC,
  - `bounds` : [ouest, sud, est, nord] du produit,
  - `dir` : sous-répertoire des dalles de la couche,
  - `tiles` : dictionnaire `"iy_ix"` → objet
    `{file, lat0, lng0, valid_ratio, depth_min, depth_max}`
    (lat0/lng0 = coin nord-ouest ; valid_ratio = % de cellules non-NaN —
    permet au moteur d'écarter d'office les dalles quasi vides ;
    depth_min/max = contrôle qualité rapide).

Règle de lecture multi-couches (si HOMONIM ajouté) : pour un point donné,
**la couche la plus fine qui possède la dalle GAGNE, et ses NaN ne sont
JAMAIS rebouchés** par la couche grossière (le 100 m lisse les côtes :
reboucher rouvrirait des îlots). C'est la règle MosaicGrid de SignalMar.

### 7.3 Compression (option)
`.npy` brut = memmap possible (recommandé). Si le poids disque prime,
`numpy.savez_compressed` (.npz, ~40-60 % de gain sur les zones à NaN)
mais PERTE du memmap (décompression à l'ouverture). Choisir selon la
machine cible ; ne pas mélanger les deux formats dans un même index.

## 8. Chargement côté moteur de routage (contrat)

1. Charger `index.json` une fois au démarrage.
2. Pour une fenêtre de calcul (bbox) : lister les dalles intersectantes
   par simple arithmétique d'indices (`floor(lng/0.1)` etc.) — pas de
   R-tree nécessaire à cette échelle.
3. memmap des `.npy` retenus ; profondeur d'un point =
   dalle contenant le point → cellule `r = floor((lat0 − lat)/0.0002)`,
   `c = floor((lng − lng0)/0.0002)`.
4. Dalle absente de l'index = hors couverture = NaN = interdit.
5. Si sous-échantillonnage nécessaire pour l'A* (grosses fenêtres) :
   **max-pooling de la PROFONDEUR minimale** (garder le fond le MOINS
   profond du bloc) — jamais de moyenne : une roche de 20 m doit survivre.

## 9. Post-traitements OBLIGATOIRES avant navigation (leçons SignalMar)

1. **Masque des îles OSM « baké »** : le MNT TANDEM donne de l'EAU sur des
   îlots réels (mesuré : Er Lannic 0,4-3,6 m de « fond » SUR l'île).
   Récupérer les polygones `place=island/islet` via l'API Overpass d'OSM
   sur l'emprise, rasteriser au pas de la grille, forcer NaN dans les
   dalles. Toujours conserver les dalles brutes (`*_orig`) à côté.
2. **Auto-vérification** : après bake, échantillonner chaque île de
   référence (Arz, Er Lannic, Houat, Hoëdic, Belle-Île…) tous les ~10 m et
   vérifier 0 cellule « eau » sur la terre.
3. **Marée** : les profondeurs sont PBMA (quasi plus basses mers). Le
   moteur ajoute la hauteur de marée du moment — jamais le script de
   dallage (les dalles restent intemporelles).

## 10. Contrôles qualité (valeurs de référence mesurées dans SignalMar)

À vérifier après dallage (tolérance ±0,05 m, mêmes données source) :
- Chenal de Port-Navalo (47.5445, −2.9210) → **19,36 m**.
- Approche Le Palais, Belle-Île (47.3480, −3.1440) → **5,80 m**.
- Passage de la Teignouse (47.4550, −3.0470) → **11,85 m**.
- Île d'Arz, à terre (47.5930, −2.8020) → **NaN**.
- Statistiques globales attendues (TANDEM entier) : grille 2626×4834,
  ~51 Mo en un bloc, profondeur min < 0 possible (estran découvrant,
  valeurs négatives = au-dessus du ZH → à conserver telles quelles, le
  moteur les traite avec la marée).

## 11. Ordre d'exécution du script (résumé)

`télécharger (reprise Range) → extraire → lire .asc → nodata/1e30 → NaN →
profondeur = −altitude → découper en dalles 0.1° → écrire .npy manquants
uniquement (idempotent, reprise sûre) → écrire index.json → bake îles OSM →
auto-vérification îles → contrôles qualité §10 → nettoyage sources.`

Le script doit être **idempotent** : relançable après coupure sans rien
retélécharger ni recalculer ce qui existe déjà (test d'existence
dalle par dalle + `.part` pour les téléchargements).
