# SignalMar V2 — MODE NAVIGATION COMPLET : analyse de faisabilité & stratégie
(19/07/2026 — demande armateur. V1 = gelée/correctifs. Groupes & évolutions liées : EN ATTENTE jusqu'à nouvel ordre.)

## 1. Verdict global
FAISABLE, et SignalMar est bien positionné (on a déjà GPS/cap/vitesse, cône, alertes,
signalements, WebView Leaflet pilotable, backend modulaire). MAIS il y a 3 verrous
à lever et 1 risque non technique majeur (responsabilité). Il n'existe AUCUNE brique
open source « équivalent Navionics dock-to-dock » clé en main : le moteur de routage
sera développé par nous (A* sur grille de profondeur — algorithme classique, maîtrisable).

## 2. Les 3 verrous techniques
### V1 — Profondeurs BRUTES (pas des images)
Le WMS actuel ne renvoie que des IMAGES. Pour CALCULER une route il faut les valeurs :
- MNT SHOM HOMONIM en fichiers (GeoTIFF/NetCDF) : 100 m façades + 20 m côtier
  (dont MNT_COTIER_MORBIHAN_TANDEM_20m). Licence Ouverte, gratuit.
- Téléchargement : diffusion.shom.fr (compte gratuit) OU API « prépaquets » scriptable
  (services.data.shom.fr/INSPIRE/telechargement/prepackageGroup…, archives .7z).
  PAS de WCS public → ingestion CÔTÉ SERVEUR une fois pour toutes (rasterio/numpy),
  grille tuilée interrogeable (profondeur(lat,lng)).
- Volumes : Morbihan 20 m = qq dizaines de Mo ; façade ATL 100 m ≈ 10k×10k points
  ≈ 400 Mo brut (gérable, lectures fenêtrées).

### V2 — Moteur de routage « route sûre »
- Masque navigable = profondeur(ZH) ≥ tirant d'eau + marge verticale (UKC)
  + DILATATION morphologique du masque interdit = marge horizontale (curseur, mini 50 m).
- A* multi-résolution (100 m grossier → raffinement 20 m local), coût pénalisant la
  proximité des zones limites, lissage (string pulling) → sortie = liste de waypoints.
- Dangers ponctuels : seamarks OSM via Overpass (bouées, roches, épaves, obstructions)
  + signalements SignalMar actifs → injectés dans le masque/coût.
- Références open source utiles (aucune complète) : searouter-osm (A* graphe OSM,
  sans bathy), SIMROUTE (A* météo + tirant d'eau, orienté grands navires), OpenCPN
  (pas d'autorouting). → moteur custom backend Python.

### V3 — OFFLINE 100×100 km (le vrai point dur)
- Grille de profondeur offline : FACILE (pack binaire ~10-40 Mo/zone, découpé de notre
  grille serveur). Le routage offline peut tourner en local (JS) sur cette grille.
- Tuiles carte : la politique d'usage des tuiles openstreetmap.org INTERDIT le
  téléchargement en masse → 3 options : (a) auto-héberger un serveur de tuiles,
  (b) provider payant (MapTiler…), (c) pack de tuiles générées par nous.
  Volume estimé z8→z15 sur 100×100 km ≈ 8-10 000 tuiles ≈ 80-250 Mo.
- Servir des tuiles LOCALES à Leaflet dans la WebView = pont data-URL (faisable,
  perfs moyennes). Solution PROPRE = MapLibre GL natif + packs offline → DEV BUILD
  obligatoire (adieu Expo Go pour tester). DÉCISION D'ARCHITECTURE à trancher en N3,
  APRÈS le POC en ligne.
- MAJ SHOM : les fiches GeoNetwork des produits sont datées/versionnées → date du
  produit stockée dans le pack, comparaison au boot → bannière « carte périmée ».

## 3. Risques & limites (objectif)
1. **Responsabilité juridique (LE risque n°1)** : suggérer des « routes sûres » avec des
   données « non utilisables pour la navigation officielle » (mention SHOM obligatoire).
   Mesures : consentement explicite par session, marges conservatrices par défaut,
   bandeau permanent « aide à la navigation — ne remplace pas les cartes officielles »,
   bouton « danger assumé » journalisé (id user + route + timestamp). Navionics fait pareil.
2. **Marée NON gérée en V2.0** : les MNT sont référencés au ZÉRO HYDROGRAPHIQUE
   (≈ plus basse mer astronomique) → calcul par défaut ULTRA-CONSERVATEUR. Dans le
   Golfe (marnage ~5 m), des passages praticables à PM seront refusés. Acceptable en
   V2.0 (sécurité d'abord) ; V2.x : hauteur d'eau prédite (API marée SHOM = clé/licence
   à vérifier) + fenêtre horaire de passage.
3. **Pas d'ENC officielles** : les cartes vectorielles S-57 SHOM (dangers exhaustifs,
   zones réglementées) sont PAYANTES et non redistribuables. Nos dangers = MNT (le
   relief 20 m capture roches/hauts-fonds) + seamarks OSM (qualité variable, incomplet)
   + signalements SignalMar. Limite à assumer et à afficher.
4. **Perfs mobiles** : calcul serveur (rapide) en ligne ; en offline, A* local sur
   grille 20 m à borner (zone 100×100 → grille 5000×5000 → multi-résolution requise).
5. **Dette frontend BLOQUANTE** : map.tsx = 2 794 lignes, MarineMap.tsx = 1 966.
   Ajouter le module nav sans refactor préalable = risque maximal de régression
   (interdite). Refactor N0 obligatoire, à ISO-fonctionnalités, testé.

## 4. Les PLUS
- Différenciateur énorme vs V1 ; données 100 % gratuites (SHOM open data, OSM).
- 60 % de la matière existe déjà : GPS/cap/vitesse lissés, cône & couloir (réutilisable
  pour le corridor de route), alertes vocales le long de la route, signalements natifs,
  clic long déjà câblé (menu à enrichir « Signaler ici / Naviguer ici »), MarineSlider
  (tirant d'eau/marge), backend modulaire (nouveau routers/routing.py + core/bathy.py
  sans toucher l'existant).
- L'armateur = testeur expert (Navionics/Garmin) → boucle de validation terrain crédible.

## 5. Stratégie par phases (chaque phase testable)
- **N0 — Préparation (1 session)** : curseur d'opacité bathy temps réel (demandé),
  refactor map.tsx/MarineMap en modules SANS changement fonctionnel (tests de
  non-régression), réglages bateau dans Profil (tirant d'eau, marge latérale ≥ 50 m),
  clic long → menu 2 choix.
- **N1 — Moteur de route (2-3 sessions)** : ingestion MNT (Morbihan 20 m + ATL 100 m)
  côté serveur, masque navigable + A* + lissage, POST /api/routes/compute
  {A, B, tirant, marge} → waypoints + profil de profondeur, affichage route sur la
  carte. ZONE PILOTE = Morbihan (tests comparatifs armateur).
- **N2 — Édition & sécurité (1-2 sessions)** : tap sur la route = waypoint, drag =
  déplacement avec RE-VALIDATION du segment (vert/orange/rouge), override « danger
  assumé » avec consentement, signalements SignalMar dans le corridor + alertes
  en cours de route, disclaimers/CGU.
- **N3 — Offline (2-3 sessions + décision d'archi)** : sélecteur de zone 100×100 km
  (carré déplaçable/zoomable), pack profondeurs + tuiles, routage local, détection
  MAJ SHOM. Décision WebView-Leaflet vs MapLibre natif (build) AVANT cette phase.
- **N4 — Affinage** : marée/fenêtres horaires, nature des fonds, couverture nationale,
  export/partage de routes.

## 6. Décisions demandées à l'armateur
1. Zone pilote Morbihan d'abord ? (recommandé)
2. V2.0 sans marée = profondeurs « pire cas » (conservateur) : acceptable pour commencer ?
3. Offline : d'accord pour trancher WebView vs moteur natif APRÈS le POC en ligne (N1/N2) ?
4. GO pour N0 tout de suite (curseur opacité + refactor + réglages bateau) ?
