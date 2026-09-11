# SignalMar — PRD

## ✅ ITER167 (10/09, RÉPARATION 3 POINTS CRITIQUES — preuves zip 10.09 armateur)
- CAUSE 1 « HALLUCINATION PROFONDEURS » (reproduite au point exact des
  captures, Pointe de Saint-Nicolas/Arzon) : la règle « minimum dans un
  rayon de 25 m » du /api/bathy/depth (29/07) prenait la cellule VOISINE la
  moins profonde — chenaux à fort gradient (maille 20 m : 0,1→18,5 m en
  200 m) → affichait 5,1 m pour 17,9 m réels, en CONTRADICTION avec nos
  isobathes. FIX : interpolation BILINÉAIRE des 4 cellules encadrantes
  (convention exacte de contourpy), bornée min(cellule proche). Vérifié :
  19,0 m au point des captures (avant 5-7 m).
- CAUSE 2 « TORCHON VISUEL » : les tuiles orange/rouges pixélisées des
  captures = le WMS SHOM lui-même (relief TERRESTRE du MNT + trous de
  tuiles amont + emprise fine limitée au Morbihan + « 1 couche à la fois »
  qui vidait tout hors zone). FIX : NOUVEAU calque « maison »
  GET /api/tiles/bathy-local/{z}/{x}/{y}.png — rendu depuis la MOSAÏQUE
  SHOM LOCALE (TANDEM 20 m > Litto3D 20 m > ATL 100 m), interpolation
  bilinéaire LISSE (zéro Minecraft), palette bleue continue type SHOM,
  estran vert pâle, TERRE TRANSPARENTE, cache disque 30 j, cohérent goutte
  d'eau/isobathes (même mosaïque). bathy.ts réécrit : UNE couche
  bathy-local (bounds façade [45.70,-5.45]→[49.01,-1.0], maxNativeZoom 15,
  maxZoom 21) remplace les 4 WMS ; _pickBathyLayer/_syncBathy supprimés.
  Isobathes : niveau 25 m ajouté (z13/z14/MAX).
- CAUSE 3 « LENTEUR » (67 s moteur J, capture R-20260910-074230-M5) :
  RemoteGrid.window() RÉASSEMBLAIT les dalles OVH à CHAQUE appel (dizaines
  de fenêtres recouvrantes par calcul : passe grossière, raffinements,
  couloirs). FIX tile_bathy.py : CACHE des 3 derniers assemblages (marge
  25 %, réutilisé si bbox contenue à k ≤ requis) — validé sur store
  synthétique : recouvrement bit-identique, sous-fenêtres servies en ~0 ms
  (une différence d'1 colonne de BORD possible = sensibilité flottante
  préexistante des bords de fenêtre). prefetch 8→16 threads.
  + Téléchargement de zone côté APP (200 Mo en 3 min 25 → note n°1) :
  downloadDalles passe en 5 téléchargements PARALLÈLES.
- AUCUN calcul de route exécuté (interdiction armateur) — validations en
  lecture seule + store synthétique uniquement. test_tile_reader 8/8,
  iter165 4/4, lint OK. NB : OVH injoignable depuis le pod au moment du
  test (repli Moteur I documenté inchangé).

## ✅ ITER166 (10/09, V1.6 FINALE — refonte visuelle + prépa build APK, ordre armateur)
- ACTION 1 (déjà ITER165 sauf WMS) : rendu .npy désactivé ✔ ; NOUVEAU :
  calque WMS SHOM GÉNÉRALISÉ à toute la France — bornes façade ATL élargies
  [[41.0,-7.5],[51.6,2.8]] (bathy.ts), HOMONIM ATL couvre Atlantique +
  Manche + Mer du Nord (vérifié : tuiles Cherbourg 70 Ko et Dunkerque 83 Ko
  servies via /api/tiles/shom/atl). Rôles : WMS = visuel, dalles .npy =
  calcul + goutte d'eau uniquement.
- ACTION 2 : « Ok j'ai compris » supprimé ✔ (ITER165), chrono « Calculé en
  X.X s » ✔ ; NOUVEAU : bouton STOP sur TOUS les écrans de calcul —
  anyBusy = routeBusy|manualBusy|editBusy|compareBusy (map.tsx) → pill
  chrono + ARRÊTER LE CALCUL pour route auto, création manuelle,
  modification de points (User), recalcul autre moteur (Admin), route
  enregistrée rejouée. CancelToken propagé : api.manualRoute et
  api.recomputeSavedRoute acceptent cancel (client.ts) ; catch cancelled →
  toast info « Calcul arrêté. ». editBusy déclaré avant le chrono ;
  netQuiet={anyBusy}. NOUVEAU : RÈGLE DES 150 % SUPPRIMÉE POUR TOUS LES
  MOTEURS (routing.py : blocs low_margin auto + manuel retirés) — seuls
  tirant + marge saisis comptent.
- ACTION 3 : bouton Cartes 📥 + carré 50 km + pack (dalles + balisage/
  mouillages/dangers) + pastille LOCAL/SERVER + zoom z21 ✔ (déjà ITER165,
  vérifié).
- ACTION 4 : A* Moteur J (2.0, 50 000) ✔ (déjà ITER164, vérifié).
- AUCUN calcul de route exécuté. iter165 pytest 4/4, lint OK, smoke OK.
- PRÉPA PUBLICATION/APK (deployment_agent, 4 passes → statut WARN seulement) :
  · app.json splash → splash-image.png (le fichier splash-icon.png manquait) ;
  · PLUS AUCUNE suppression auto en base : TTL computed_routes/support_
    screenshots retirés + drop idempotent au boot, _archive_loop = update_many
    seul (les lectures filtrent expires_at), purge support_uploads = soft-
    delete {purged:true} + nettoyage disque seulement ;
  · JWT_SECRET requis de l'env (plus de fallback), TEST_PASSWORD sorti du
    code → env (backend/.env en dev, Secrets en prod — sans lui le seed QA
    est inerte), .gitignore sans patterns .env, METRO_CACHE_ROOT quoté ;
  · push iOS early-return (pas de GoogleService-Info.plist — Android seul),
    URL Play Store page parrain → id=com.emergent.signmarwazemer.sa5b3v ;
  · expo ~54.0.37 / expo-constants ~18.0.14 / expo-file-system ~19.0.24.
  ⚠️ À la publication : saisir JWT_SECRET, TEST_PASSWORD, TILE_SERVER_TOKEN
  dans Publish → Deploy → Secrets.

## ✅ ITER165 (09/09, V1.6 — REFONTE UI/UX + DONNÉES LOCALES armateur)
- A1 (RouteCard) : accusé « Ok, j'ai compris » SUPPRIMÉ (props acknowledged/
  onAcknowledge + styles ack*/followBtnOff retirés) → accès DIRECT : bouton
  vert « Suivre cette route » + bouton « Enregistrer cette route »
  (route-save-big). CHRONO FINAL sous le titre : « Calculé en X.X s »
  (route-compute-time, prop computeS ← routeComputeS posé à chaque calcul).
- A2 (Cartes 📥) : bouton « Cartes 📥 » EN BAS À GAUCHE (cartes-btn, styles
  cartesWrap left:10 bottom:44) → window.__zoneStart() (nouveau module JS
  zone-picker.ts injecté dans leaflet-html) : CARRÉ semi-transparent de
  50 km de rayon centré sur la vue, 4 COINS DRAGGABLES (postMsg
  zone_corners → onZoneCorners → état zoneCorners). Barre offline-zone-bar :
  « Lancer le téléchargement » = analyse (dalles-list?poly=4 coins) puis
  PACK COMPLET : dalles .npy + balisage/mouillages/dangers
  (downloadSeamarkPack → /api/bathy/seamarks?bbox&limit=5000 → JSON
  pack_seamarks.json sur l'appareil) + progression en Mo. L'ancienne entrée
  appui-long « Cartes hors ligne » (ITER164) est SUPPRIMÉE.
  Backend : /api/bathy/seamarks accepte limit (600 défaut, max 5000).
- A3 (VISUEL) : rendu visuel des dalles .npy DÉSACTIVÉ (« adieu Minecraft »)
  → bathy.ts revenu au WMS SHOM officiel (atl/gdl/corse + morbihan bornes
  STATIQUES, élargissement dynamique ITER162 retiré). L'endpoint
  /api/tiles/dalles reste servi côté backend (inutilisé par la carte).
  Zoom conservé jusqu'à z21 (~10 m). NETTOYAGE CLIC : mini-popup clic carte
  (coordonnées/hauteur/photo, mapTapInfo + capture support admin) SUPPRIMÉ —
  un clic ne déclenche plus rien ; seule la GOUTTE D'EAU (bouton) mesure.
- A4 (HORS LIGNE) : préchargement auto de tuiles au démarrage DÉSACTIVÉ
  (prefetch.ts : __prefetchAroundUser inerte sauf window.__prefetchOn) ;
  fond de carte basique OSM chargé à la demande (bathy OFF par défaut).
  PASTILLE SOURCE (data-source-badge) sous le bouton Cartes : verte
  « LOCAL » si le centre carte est couvert par une dalle stockée sur
  l'appareil (isLocalCovered + manifeste), grise « SERVER » sinon
  (badgeCenter throttlé 1 s via onMapMoved).
- A5 (PERF) : A* J (2.0, 50 000) déjà en place (ITER164) ; côté serveur les
  dalles en cache disque sont déjà utilisées en priorité (remote_cache).
- NB : Moteur I v8.1.0 INTACT (aucun fichier moteur touché à l'ITER165).
- AUCUN calcul de route exécuté.

## ✅ ITER164 (09/09, REFONTE TOTALE UI + STRATÉGIE DONNÉES armateur)
- INTÉGRITÉ : engine_i.py = 2b000634 (v8.1.0) VÉRIFIÉ intact (git diff vide).
- ACTION 1 (UI) : bandeau unique/chrono/STOP/tirant/ⓘ/menu = déjà ITER163.
  NOUVEAU : après STOP → bandeau « Calcul arrêté » (routeRetry reason:"stop")
  avec Réessayer + Replacer le départ (User) + « Changer de moteur »
  (route-retry-engine, ADMIN uniquement → /profile/settings).
- ACTION 2 (MASTER PLAN données) :
  · Outil de sélection de zone : appui long → menu « Cartes hors ligne »
    (longpress-offline-zone) → sommets du polygone par appuis longs
    (affichés via prop manualPoints), barre offline-zone-bar : « Analyser la
    zone » (≥3 pts) → GET /api/tiles/dalles-list?poly=lat,lng;… (nb dalles +
    Mo) → « Télécharger » avec barre de progression → dalles .npy stockées
    sur l'appareil (expo-file-system/legacy, documentDirectory/dalles/ +
    manifeste AsyncStorage sm.offline.dalles). Lib : src/lib/offline-dalles.ts.
    NB : téléchargement natif (Expo Go/APK) — pas sur le web preview.
  · Backend : GET /api/tiles/dalles-list?poly=, GET /api/tiles/dalles-npy/
    {name} (sert le .npy, 1 000 128 o, testé), GET /api/tiles/dalles-fine-list
    ?bbox= (lit la clé « tiles_fine » de l'index OVH si publiée — [] sinon).
  · Dalles fines 5 m/2 m AUTO : checkFineTiles() après chaque téléchargement
    de zone — INERTE tant que l'index OVH v2 ne publie pas « tiles_fine »
    (scaffold prêt pour la chaîne PC v3 de l'armateur).
  · VISUEL : DALLES_MIN_Z 10 → 8 (calque dalles « partout en France » dès z8,
    fini le flou ATL 100 m au zoom) ; _CLEAR_PNG alpha 0 (le _BLANK_PNG
    historique était à 50 %).
  · ZOOM : carte jusqu'à z21 (échelle ~10 m) — L.map maxZoom 21, OSM/seamark/
    bathy maxNativeZoom 19/18/19 (agrandissement au-delà).
- ACTION 3 (PERF MOTEUR) : calcul unique + 150 % désactivée = déjà ITER163.
  NOUVEAU : A* PONDÉRÉ Moteur J UNIQUEMENT — ContextVar ASTAR_TUNING dans
  signalmar_v1/core.py (défaut None → A-I identiques bit à bit, vérifié sur
  grille synthétique), armé par engine_j.py à (2.0, 50 000) : poids
  heuristique 2.0 + plafond 50 000 nœuds. Kernel numba recompilé OK.
- AUCUN calcul de route moteur exécuté (test A* = grille synthétique 12×12).

## ✅ ITER163 (08/09, MISSION REMISE À PLAT RADICALE armateur) — Industrial Stable
1. INTÉGRITÉ : engine_i.py RESTAURÉ à v8.1.0 stable (git checkout 2b000634 —
   les 2 retouches ITER162 need_zh/_marks_strict_ok retirées). Moteur I =
   « Moteur Sûr Local » intouchable. engine_j.py (héritage I) inchangé.
2. SIMPLIFICATION CALCUL (routers/routing.py, simple_mode = algo signalmar.i
   ou signalmar.j) : UN SEUL calcul direct au ZH (plus de double exécution
   ZH/marée), pas de dernier recours (mouillages/côtés), pas de mode « eau
   peu profonde », pas de route de secours rouge, pas de calcul hypothétique
   marée sur échec, RÈGLE DES 150 % (low_margin/route plus sûre) DÉSACTIVÉE
   (auto + manuel). Échec → 422 propre « Pas de route trouvée : aucun passage
   ne respecte à la fois le fond (tirant+marge) et le balisage ». Paliers de
   marge latérale conservés (réduction annoncée, jamais d'ajout). Moteurs
   A-H : comportement cascade historique INCHANGÉ.
3. UI/CHRONO/LOGS : chrono visible pendant le calcul (route-busy-chrono) +
   bouton ARRÊTER LE CALCUL (route-stop-btn, CancelToken dans runAsJob →
   rend la main immédiatement). Temps effectif loggé (console + logger
   route_computed: compute_s serveur + elapsed_s appareil). POPUPS FUSIONNÉS :
   LowMarginModal + SaferPreviewModal SUPPRIMÉS (fichiers effacés), bandeau
   unique « Route conseillée » (RouteCard) avec tirant d'eau (prop draftM),
   infobulle ⓘ décharge de responsabilité (route-disclaimer), menu dépliable
   Actions : Enregistrer / Modifier (entre en édition) / Partager
   (Share natif) / Supprimer. safety_extra_m/preview retirés du flux front.
4. VISUEL DALLES : NOUVEAU GET /api/tiles/dalles/{z}/{x}/{y}.png (tiles.py) —
   calque bleu RENDU depuis les dalles OVH (RemoteGrid.sample 256², colormap
   6 paliers clair→foncé, estran vert, NaN transparent, cache disque par
   version d'index, z<10 → tuile transparente). bathy.ts : couche fine =
   dalles (bounds dynamiques tiles-source conservés), _pickBathyLayer z≥10,
   sync sur zoomend. WMS morbihan abandonné côté carte.
5. BALISES : ingest_seamarks.py --zone dalles (emprise dérivée de
   remote_cache/index.json ≈ 43.3→48.99 / −5.4→−1.0) → seamarks.json étendu
   à TOUTE la couverture dalles (Gascogne comprise). NB : Grégan (cardinale
   sud 47.5652, −2.9172) était DÉJÀ présent en base et servi par
   /api/bathy/seamarks (vérifié) — le « manquant » côté armateur venait
   probablement d'une version déployée antérieure.
- ⚠️ PIÈGE ÉVITÉ/DOCUMENTÉ : édition parallèle (search_replace + sed -i) du
  MÊME fichier = corruption (map.tsx tronqué) → restauré de git puis édits
  séquentiels. NE JAMAIS éditer un même fichier en parallèle.
- AUCUN calcul de route exécuté (ordre armateur). Testing agent : contrôle
  STATIQUE + endpoints non-invasifs uniquement.

## ✅ ITER162 (04/09, 5 correctifs armateur) — Moteur J / backend / carte
1. SÉCURITÉ (engine_i.py _complete_truncated_end, hérité par J) : seuil de
   sonde du raccordement final = tirant + marge au ZH (need_zh), plus
   seulement terre (−3,5 m). Coupe au dernier point SÛR ; end_snapped
   reason « arrivee_trop_peu_profonde » (vs « arrivee_a_terre » si terre)
   + warning dédié. Marée non créditée (conservateur, signature inchangée).
2. VITESSE (tile_bathy.py) : RemoteTileBathy._ensure_file + prefetch
   (ThreadPoolExecutor 8) appelé par RemoteGrid._assemble ET sample —
   fenêtre 12 dalles téléchargée en 1,25 s (vs séquentiel).
3. FIABILITÉ (tile_bathy.py) : RemoteGrid.grids (grilles SHOM locales via
   GRID_OVERRIDE=None temporaire — champs heuristiques abris/direction
   identiques au Moteur I, évite d'assembler 2,4 Go) + .grid (tableau de
   la plus fine) → plus d'AttributeError signalmar_v3/direction.
4. LOGIQUE (engine_i.py _marks_strict_ok, assoupli sur ordre) : côté/
   secteur INCONNU ≠ refus d'office — accepté si écart ≥ 50 m
   (_UNKNOWN_MARK_CLEAR_M), refusé sinon ; côtés CONNUS toujours stricts
   (supprime les crochets type Drennec).
5. VISUEL : /api/bathy/tiles-source expose bounds [w,s,e,n] de l'index OVH
   ([-5.3,43.3,-1.0,48.9]) ; marine-map/js/bathy.ts les lit au chargement
   et remplace les bornes Morbihan de la couche fine (repli statique si
   échec). NB : le raster WMS SHOM « morbihan » ne couvre pas plus large —
   bornes élargies = sélection de couche, pas de nouvelles tuiles.
- Testing agent (SANS calcul de route, ordre respecté) : backend 100 %,
  frontend 100 %, tile_reader 8/8 — /app/test_reports/iteration_156.json.
  engine_f_frozen intouché. AUCUN calcul de route exécuté.

## ✅ ITER161 (04/09, GO armateur) — MOTEUR J : Moteur I sur dalles OVH
- core/bathy.py : GRID_OVERRIDE (ContextVar, défaut None → A-I inchangés) ;
  get_grid() renvoie l'override s'il est posé (mécanique SIDE_RULES_OPEN).
- core/tile_bathy.py : RemoteGrid = adaptateur API MosaicGrid complet sur
  les dalles OVH (depth_at/covers/sample vectorisé groupé par dalle/
  window : assemblage des dalles intersectantes en _MemGrid (héritage
  BathyGrid pour décimation+pool), dalles manquantes → NaN, pré-pooling
  nanmax si > 256 dalles pleine résolution). get_remote_grid() singleton
  (cooldown 120 s si serveur muet).
- core/nav/engine_j.py (NOUVEAU) : EngineJ(EngineI) algo signalmar.j —
  pose GRID_OVERRIDE=RemoteGrid le temps du calcul, warning « Bathy :
  Serveur OVH (v2.0)… » ; si OVH injoignable → repli mosaïque locale
  (résultat = Moteur I) + warning explicite. AUCUNE copie de code moteur.
- Registre algos + seed Mongo engine_j « Moteur J dalles OVH 04.09.26 »
  (parent engine_i, actif → visible sélecteur mobile). Vérifié : registre
  10 algos, doc en base, override on/off OK, sample/window OK (Teignouse
  OVH 11,42 vs mosaïque 11,85 — écarts = données armateur, voulus pour la
  comparaison). engine_f_frozen.py et engine_i.py NON modifiés (git).
- AUCUN calcul de route exécuté (ordre armateur — il compare sur la carte).
  Tests test_tile_reader 8/8 verts, backend démarré proprement.

## ✅ ITER160 (04/09) — BRANCHEMENT DISTANT dalles OVH (tile_bathy v2) + popup Source
- core/tile_bathy.py : RemoteTileBathy (index v2 PLAT du serveur armateur
  https://…/signalmar_datas/tiles/, 1983 dalles France, ?token= via env
  TILE_SERVER_TOKEN, nommage tile_{lat_sw}_{lng_sw}.npy multiples exacts
  0.1°) — téléchargement à la demande persisté dans data/tiles/remote_cache/
  (jamais retéléchargé), memmap LRU 64, cooldown 120 s sur échec.
  TileService singleton : OVH d'abord, REPLI archive locale
  (data/tiles/tandem_20m) si serveur muet, re-sonde toutes les 120 s.
- routers/bathy.py : GET /api/bathy/tiles-source → {source, label
  « Serveur OVH (v2.0) » / « Archive (Repli) », version, tiles_indexed,
  tiles_cached}. Frontend : api.tilesSource() + ligne « Source : … » dans
  RouteCard (testID route-tile-source).
- .env : TILE_SERVER_URL ajouté (URL OVH). Vérifié e2e : source ovh,
  3 dalles en cache après lecture, repli testé avec URL invalide.
- ⚠️ SIGNALÉ ARMATEUR : les dalles v2 OVH DIVERGENT de la mosaïque SHOM
  locale (Port-Navalo 14,63 m vs 19,36 m ; Teignouse 11,42 vs 11,85) —
  probable rééchantillonnage façade 100 m dans sa chaîne PC v2. AUCUN
  moteur (A-I) ne consomme ces dalles : logique v8.1.0 intacte.
- Tests : test_tile_reader 8/8 verts (archive locale inchangée), lint OK.

## ✅ ITER159 (03/09) — TILE_SERVER_TOKEN ajouté au backend/.env (dev)
- Clé TILE_SERVER_TOKEN ajoutée à backend/.env (quotes simples : $ et &
  préservés, vérifié via dotenv, 40 caractères, valeur jamais affichée).
- Secrets de DÉPLOIEMENT : non modifiables par l'agent — l'armateur doit
  la saisir via Publish → Deploy → Secrets (les nouvelles clés du .env
  local sont reprises au deploy, valeurs existantes non écrasées).
- Aucun code ne consomme encore cette clé (préparation serveur de dalles).

## ✅ ITER158 (03/09) — Lecteur de dalles PC (core/tile_bathy.py) + dalles test armateur
- Dalles PC armateur reçues dans data/tiles/tandem_20m/ (index.json 71
  dalles, qa_report PASS 4/4, 4 dalles finales + 2 _orig zone Lorient/Étel).
  Intégrité vérifiée : bit-identiques à la mosaïque SignalMar (2000 pts,
  écart 0,000 m), bake îles conforme (1022/13 cellules = index).
- NOUVEAU core/tile_bathy.py : TileBathy (API alignée MosaicGrid) —
  depth_at (couche la plus fine gagne, NaN jamais rebouché), memmap LRU 64,
  résolution point→dalle avec fallback 8 voisines (coins décalés d'une
  fraction de cellule, ex. lng0=-3.20003), fichiers absents de l'index
  tolérés (livraison partielle → stats()["missing_files"]), tiles_for_bbox.
- tests/test_tile_reader.py : 8/8 verts, 100 % local (aucun réseau, aucun
  calcul de route, aucun moteur sollicité).
- ⚠️ AUCUN moteur (A-I) ne consomme tile_bathy — branchement futur sur GO
  explicite. Prochaine étape annoncée par l'armateur : validation carte
  Moteur I v8.1.0 (Roguedas/N4/Illur 1 m et 2 m).

## ✅ ITER157 (03/09) — SPEC document dallage bathy PC (AUCUN code app)
- Demande armateur : documenter la procédure SHOM complète (connexion,
  formats, transformation) pour écrire lui-même un script PC Windows de
  dallage 10/20 km en .npy. Livré : /app/memory/SPEC_DALLAGE_BATHY_PC.md.
- URLs SHOM re-vérifiées en live (HTTP 200, Accept-Ranges) :
  TANDEM Morbihan 20 m PBMA (105 Mo) groupe
  MNT_COTIER_MORBIHAN_TANDEM_20m_PBMA_4326_PACK_DL, HOMONIM ATL 100 m
  (464 Mo) groupe MNT_ATL100m_HOMONIM_PBMA_4326_PACK_DL, Litto3D BZH
  groupe LITTO3D_BZH_2018_2021_PACK_DL (dalles 5 km L93).
- Points de contrôle QA mesurés sur la mosaïque actuelle (lecture seule,
  aucun calcul de route) : Port-Navalo 19,36 m ; Le Palais 5,80 m ;
  Teignouse 11,85 m ; île d'Arz NaN.
- Aucun fichier de code modifié. Moteur I v8.1.0 toujours EN ATTENTE de
  validation carte armateur (Roguedas/N4/Illur 1 m et 2 m).

## ✅ ITER156 (02/09) — fix 500 : RouteError("no_route", message) dans la garde balisage du Moteur I
- La garde « Pas de route trouvée » (engine_i.py L894) levait
  RouteError(message) alors que la signature est RouteError(code, message,
  payload=None) → TypeError → HTTP 500. Fix (demandé par l'armateur) :
  code "no_route" ajouté en 1er argument — choix DÉLIBÉRÉ : avec ce code,
  la cascade API peut tenter la route de secours (« route rouge ») même en
  conflit de balisage. NB : le verrou SIDE_RULES_OPEN=False du Moteur I
  reste actif — la route de secours du Moteur I respecte toujours les
  côtés de balises ; si aucune n'existe, 422 propre (plus de 500).
- Aucun test exécuté (ordre armateur), compilation + import OK, backend
  redémarré (sudo supervisorctl restart backend).

## ✅ ITER155 (02/09, GO armateur) — MOTEUR I v8.1.0 : VERROU DERNIER RECOURS + début nettoyage tests
- VERROU (engine_i.py uniquement) : EngineI.compute_auto force
  SIDE_RULES_OPEN=False (_SIDE_RULES_OPEN.set(False)) autour de TOUT le
  calcul (_compute_locked) : même quand la cascade API arme le « dernier
  recours » ou le mode « eau peu profonde » (SIDE_RULES_OPEN=True dans
  routers/routing.py, INCHANGÉ), le Moteur I referme les règles de côté.
  Une route dégradée qui couperait le balisage est donc impossible pour
  le Moteur I → à défaut « Pas de route trouvée ». MOORINGS_OPEN
  (mouillages) reste géré par la cascade (pas une règle de balisage).
  Les moteurs A-H conservent le comportement cascade historique.
- NETTOYAGE TESTS (limité au STATIQUE, ordre armateur = aucun calcul) :
  tests/archive/ créé ; scripts de debug repro_vilaine*.py déplacés
  (3 fichiers, pas des tests). Collect-only : 884 tests, 0 erreur
  d'import. Le tri des échecs connus (marée désactivée, seeds démo,
  rate-limit — 8 pré-existants documentés) NÉCESSITE une exécution de la
  suite → EN ATTENTE du GO armateur post-validation carte.
- ORDRE ARMATEUR RÉITÉRÉ : aucun calcul, aucun testing agent — il valide
  lui-même sur la carte. Compilation + import vérifiés, backend redémarré.

## ✅ ITER154 (02/09, remise à plat armateur) — MOTEUR I v8.0.0 : PRIORITÉ ABSOLUE AU BALISAGE
Notes armateur (zip 02.09, Golfe/Crouesty) : comportement INVERSÉ — à
tirant 2 m le Moteur I coupait Roguedas/N4/Illur que le tirant 1 m
respectait. CAUSE IDENTIFIÉE : à fort tirant l'A* détourne plus, le
redressement 80 m raccourcissait, et le contrôle de côté des cordes
IGNORAIT les balises à direction « non fiable » (u=None → bénéfice du
doute) → la corde coupait la bouée. Fait (engine_i.py uniquement) :
1. SUPPRIMÉS (ordre armateur) : « dédoublonnage intelligent »
  (_suspect_duplicate_ids), bypass « détour fantôme Errants »
  (_bypass_suspect_detours), filtrage des flags (_strip_suspect_wrong_
  sides) — ils masquaient de vraies balises. Fichier 1688 → ~1500 lignes.
2. _marks_strict_ok (nouveau, câblé sur TOUTES les modifications :
  cordes du redressement + segments du repoussement) : latérale ou
  cardinale à ≤ 150 m dont le côté/secteur est INCONNU ou NON RESPECTÉ →
  modification REFUSÉE. Inconnu = interdit, plus jamais de bénéfice du
  doute. Le fond ne compense JAMAIS le balisage (besoin d'eau ↑ → passage
  plus profond cherché, jamais de balise coupée pour compenser).
3. GARDE FINALE : après l'audit rectifié, s'il reste UNE balise coupée →
  RouteError « Pas de route trouvée : impossible … sans passer du MAUVAIS
  CÔTÉ du balisage (…) ». ATTENTION (dit à l'armateur) : la cascade API
  peut alors enchaîner sur ses paliers dégradés (dernier recours ouvre
  les règles de côté, routers/routing.py hors périmètre moteur).
4. Pipeline v8.0.0 : F pur → redressement > 80 m (strict) → écart 50 m
  latérales+cardinales (strict) → audit rectifié → garde « pas de route ».
- Tests : test_iter147 SUPPRIMÉ (testait le dédoublonnage retiré) ;
  nouveau tests/test_iter154_moteur_i_balisage_absolu.py (3 tests : I
  jamais pire que F à Lorient, tirant 2 m sans balise coupée ou refus
  net, Arradon 66 km stable) — ÉCRIT SANS EXÉCUTION (ordre armateur).
- AUCUN calcul exécuté ; compilation + import OK ; backend redémarré.
  EN ATTENTE : validation carte armateur (Roguedas/N4/Illur à 1 m ET 2 m).

## ✅ ITER153 (01/09 soir, GO armateur points 1+2) — MOTEUR I v7.4.0 : seuil 80 m + cardinales à la règle carte
- Point 1 : _DETOUR_GAIN_M 500 → 80 m — TOUT zigzag > 80 m est redressé
  par la corde directe si elle est strictement sûre (fond, portes, écarts,
  latérales fiables, mouillages/dangers, fond jamais dégradé).
- Point 2 : au passage d'une cardinale, la contrainte devient LA RÈGLE
  CARTE (bon secteur via _cardinal_ok, rayon 200 m + écart ≥ 50 m) au lieu
  du coloriage par grille : _enforce_lateral_clearance étendu aux
  CARDINALES (repoussement à max(50 m, écart recommandé)), _cardinal_ok
  ajouté aux segments modifiés du repoussement ET à la corde du bypass
  Errants (5 points de contrôle au total). Le demi-plan rasterisé de l'A*
  (F gelé) reste en amont, mais le post-traitement efface ses artefacts
  de maille (goulot Creizic Sud).
- AUCUN calcul exécuté (ordre armateur — il teste Berder → Roguedas et la
  route jumelle sur la carte). Compilation + import OK, backend redémarré.
- Analyse comparative I vs B livrée à l'armateur (tableau) : B = fond SHOM
  + marges + écart balises + sectionnement, AUCUNE règle de côté ; I = idem
  B + côtés latérales/cardinales + sidefix + dédoublonnage + audits
  rectifiés + redressement 80 m + écart 50 m.

## ✅ ITER152 (01/09, ordre armateur) — MOTEUR I v7.3.0 : correctif de STABILITÉ (Golfe / Creizic Sud)
Bug (captures) : 2 départs quasi identiques → route parfaite vs détour de
plusieurs km au goulot de la cardinale Creizic Sud. Cause : l'A* (F gelé,
intouchable) élit son couloir à la maille — à 10 m près la cellule de
départ change et le couloir bascule ; rien ne pénalise ensuite le détour.
Fait, UNIQUEMENT engine_i.py (post-traitement déterministe) :
1. _shortcut_large_detours : tout détour > 500 m (_DETOUR_GAIN_M) est
   remplacé par la corde directe (portée ≤ 4 km) SI strictement sûre —
   fond couloir ±15 m + portes (_Validator), cercles d'écart respectés
   (frôler OK, entrer jamais), latérales fiables (_seg_marks_ok),
   SECTEUR des cardinales contrôlé (_cardinal_ok : N d'une nord, S d'une
   sud, E d'une est, O d'une ouest, rayon 200 m), fond du profil jamais
   dégradé. 3 passes, plus grand détour d'abord. Warning « Détour de
   ~X m supprimé ».
2. Persistance : le redressement est indépendant de la maille → deux
   départs à 10 m convergent vers le même tracé redressé.
Ordre compute_auto : F pur → bypass Errants → REDRESSEMENT DÉTOURS →
écart latéral 50 m → ré-audit dir-coherent → strip doublons.
AUCUN calcul exécuté (ordre armateur, il reteste les 2 routes) ;
compilation + import OK, backend redémarré. EN ATTENTE : validation carte.

## ✅ ITER151 (01/09, ordre armateur) — MOTEUR I v7.2.0 : 3 règles de balisage GLOBALES
Captures armateur (Kergroise → SW, 18,3 km, I ≡ F) : faux « MAUVAIS CÔTÉ »
(Petite Jument ~61 m et No2 ~159 m du BON côté — faux couples de Lorient),
tourelle blanche Errants encore auditée, frôlements tolérés (Pengarne
35 m/53 m requis, No13 24 m/60 m). Fait, UNIQUEMENT engine_i.py :
1. DÉDOUBLONNAGE INTELLIGENT (_suspect_duplicate_ids réécrit) : homonymes
   à ≤ 500 m → la latérale AMBIGUË (couleur blanche OU inconnue/vide) est
   ignorée pour les règles de côté ; référence = latérale de couleur
   conforme (rouge bâbord/verte tribord) OU cardinale homonyme. NOUVEAU :
   la couleur vide est désormais ambiguë (les perches génériques de
   Douarnenez deviennent douteuses — voulu par l'armateur, test mis à
   jour). Groupement par NOM seul (plus par nom+catégorie).
2. AUDIT DE PROXIMITÉ RECTIFIÉ (_reaudit_dir_coherent) : wrong_side_marks
   + warnings « ⚠ MAUVAIS CÔTÉ » purgés puis REJOUÉS sous cohérence de
   direction des chenaux (DIR_COHERENCE_V6 armé → faux couples corrigés,
   même correctif que l'audit du Moteur H qui donnait 0 mauvais côté à
   Lorient). Une alerte ne part que si le tracé coupe le secteur
   RÉELLEMENT interdit.
3. ÉCART LATÉRAL MINIMAL (_enforce_lateral_clearance) : toute latérale
   frôlée < max(50 m, écart recommandé de la marque) → le point fautif est
   repoussé radialement à la bonne distance, adopté SEULEMENT si sûr
   (fond couloir ±15 m + portes via _Validator, _seg_marks_ok complet,
   fond du profil jamais dégradé) ; sinon tracé F tel quel + warning
   existant conservé. 2 passes max, refresh résultat/corridor/warnings.
Ordre dans compute_auto : F pur → bypass Errants → écart 50 m → ré-audit
dir-coherent → strip doublons (le tout sous contextvars armées, anti-
pollution caches). AUCUN calcul exécuté (ordre armateur : il teste sur la
carte) — compilation + import seuls, backend redémarré. Tests iter147 mis
à jour sans exécution (suspects : perches désormais attendues douteuses ;
identité F relâchée à ±300 m / fond jamais dégradé / pas plus de rouges ni
de mauvais côtés que F). EN ATTENTE : validation carte armateur puis
testing_agent.

## ✅ ITER150 (31/08, ORDRE armateur) — MOTEUR I : suivi des routes officielles SUPPRIMÉ INTÉGRALEMENT
- Bug armateur (captures Port-Navalo → SW Belle-Île) : Moteur I +9,3 km vs
  F, zigzags au large. Cause analysée et validée par l'armateur : le
  planificateur hérité du Moteur H accroche un système de pointillés dès
  qu'UN point passe à ≤ 3 km de la ligne directe, le suit avec un biais
  ×1,4 et peut enchaîner 3 systèmes → chenaux de la Teignouse/Houat suivis
  au large. Ce n'étaient NI les jonctions NI les lacunes NaN.
- ORDRE : supprimer INTÉGRALEMENT le principe de suivi/raccordement des
  routes officielles du Moteur I ; conserver fond SHOM, balisage, tirant
  d'eau, correctifs Errants. FAIT (engine_i.py uniquement, v7.1.0) :
  · compute_auto = _compute_base en MODE F PUR (dir_coherence off) puis
    correctifs Errants sous gardes contextvars (anti-pollution caches) ;
  · SUPPRIMÉS : _compute_with_tracks, _network_i, _plan_tracks_i,
    _join_endpoints_i, _wrong_side_i, _data_gap_only, imports safe_routes/
    _required_side/json, constantes réseau (fichier 1751 → 1417 lignes) ;
  · CONSERVÉS : _suspect_duplicate_ids, _bypass_suspect_detours (détour
    fantôme raccourci seulement si strictement sûr), _strip_suspect_
    wrong_sides. safe_routes.py/seamarks.py/moteurs A-H intacts (H garde
    SON suivi des pointillés).
- L'écrêtage au tirant d'eau du réseau de pointillés (iter147/148) n'a
  plus d'objet chez I (plus de réseau) — il reste documenté dans
  l'historique ; H conserve son écrêtage historique 0,5 m.
- Tests mis à jour SANS exécution (ordre : aucun calcul de test, armateur
  teste sur la carte) : test_iter148_e2e_armateur.py SUPPRIMÉ (spec
  obsolète) ; test_iter147 réécrit — test_engine_i_identique_f_lorient
  (I ≡ F, pas d'official_tracks ni warning écrêtage) remplace les tests
  réseau/calage ; tests Errants/fallback/suspects conservés. Seul contrôle
  effectué : compilation + import du module (aucun calcul de route).
- EN ATTENTE : validation carte par l'armateur, puis passage testing_agent
  (suites iter147 + gels) sur son accord.

## ✅ ITER149 (31/08, ordre armateur) — jobs de routage en base : fix « Calcul introuvable (expiré) »
- Cause (donnée par l'armateur, confirmée) : _JOBS en mémoire de process
  dans routers/routing.py → en production multi-instances, le POST crée le
  job sur une instance, le GET poll une autre → 404.
- Fix : collection MongoDB ``route_jobs`` partagée (_id=job_id hex, uid,
  status pending/done/error, ts datetime UTC, result/status_code/detail),
  index TTL ``ts`` expireAfterSeconds=900 (créé idempotent au 1er usage,
  purge par Mongo — même durée de relecture 15 min qu'avant, FND-012).
  _job_start (await insert), _job_run (update_one à l'issue, ts rafraîchi),
  routes_job (find_one + contrôle uid → 404 sinon). _JOBS/_jobs_gc/
  _JOBS_MAX supprimés ; _JOB_TASKS (réfs fortes asyncio) conservé.
  Concerne /compute/async ET /manual/async. Aucun changement de contrat
  API. engine_i.py et moteurs non touchés.

## ✅ ITER148 (31/08, GO armateur) — MOTEUR I : détour fantôme « Les Errants » supprimé, baseline = MOTEUR F GELÉ, comparaison F/I Lorient
- RÈGLE CONFIRMÉE PAR L'ARMATEUR : référence = Moteur F gelé (PAS H) ;
  toutes les modifications EXCLUSIVEMENT dans core/nav/engine_i.py.
- MOTEUR I restructuré, déterministe :
  · routes officielles trouvées → assemblage calé sur les pointillés
    écrêtés au besoin d'eau (contextvars cohérence armées, comme avant) ;
  · SINON → MODE F PUR direct (aucune contextvar « cohérence » armée,
    dir_coherence off) : tracé STRICTEMENT identique au F gelé, vérifié
    Arradon → Lorient 66 km (distance/fond/rouges/wrong_side égaux au
    décimètre). L'ancien essai « cohérence puis repli » donnait des
    résultats variables selon l'état des caches → supprimé ;
  · un assemblage refusé (RouteError) ne remonte JAMAIS → repli F pur
    (avant : cascade API « eau peu profonde », route ROUGE −0,27 m).
- DÉTOUR FANTÔME (doublon « Les Errants ») : post-correction géométrique
  _bypass_suspect_detours — recherche de la meilleure corde i→j (≤ 3 km,
  fenêtre 1,5 km autour du doublon, gain ≥ 40 m, tri par gain) adoptée
  UNIQUEMENT si : fond ≥ seuil couloir ±15 m + portes (_Validator), aucun
  frôlement (écart 60 m du doublon inclus), aucun mauvais côté d'une
  latérale fiable, mouillages/dangers OK (_seg_marks_ok), fond du profil
  JAMAIS dégradé. Mesuré : 1 690 → 1 625 m (zigzag fantôme supprimé), les
  VRAIES roches des Errants (0,3 m à l'ouest) restent contournées (le
  plein ouest ~900 m est refusé par la bathy — comportement correct).
  Warning : « Balisage en doublon … détour fantôme supprimé ».
  IMPORTANT (pollution inter-moteurs) : le bypass du repli F pur tourne
  sous les MÊMES contextvars que le mode v6 (sinon caches _dir_conf_*
  alimentés sur une mauvaise base → audit H variable, mesuré).
- ÉCRÊTAGE ÉTENDU : TOUS les pointillés (alignements ET tracés chartés)
  écrêtés au besoin d'eau chez I (un recommended_track passait sur des
  cellules à −0,67 m devant Kernével). Jonctions synthétiques ≤ 300 m
  désormais contrôlées AUSSI par la bathy (_join_endpoints_i(net, wet)).
- LACUNES NaN : la grille fine garde des trous 1-3 cellules en pleine eau
  (10-22 m mesurés autour) → 4 faux « tronçons rouges » sur le tracé
  officiel. Filtre _data_gap_only (tronçon acquitté si AUCUNE sonde
  mesurée < seuil et trous ≤ 60 m ; terre = NaN long/sonde < seuil →
  reste rouge) + warning honnête « Lacunes de données bathy … vérifiez À
  VUE ». Aussi : risk/compromised de l'assemblage REJOUÉS sur le tracé
  final (les index des legs ne survivent pas à la fusion — 4 faux rouges).
- COMPARAISON F/I (large → port de Lorient, draft 1,5, sans marée) :
  F : 8 862,5 m, fond mini 3,07 m, 0 rouge, 2 MAUVAIS CÔTÉS (Petite
  Jument ~51 m, N° 4 ~108 m). I : 8 922,2 m (+60 m), fond mini 7,38 m,
  0 rouge, 0 mauvais côté, calé sur 735/736/731 écrêtés à 2,0 m. JSON
  complets : /app/memory/comparaison_F_I_lorient_3108.json et
  route_I_lorient_3108.json.
- Tests iter147 étendus (8/8) : + test_fallback_jamais_pire_que_f
  (I ≡ F sur Arradon→Lorient : dist/fond/rouges/wrong_side égaux) et
  + test_errants_detour_fantome_supprime (I < F−30 m, warning, fond non
  dégradé, écart ≥ 60 m aux 2 marques, wrong_side vide).
- NOTE (préexistant, pas Moteur I) : les résultats F via API varient
  légèrement selon l'état du process (66663/2,74 vs 67204/2,2 sur
  Arradon→Lorient) — sensibilité aux caches partagés, déjà présente ;
  l'invariant testé est l'ÉGALITÉ I ≡ F dans les mêmes conditions.
  Flakiness résiduelle : test_iter143 engine_h Lorient échoue PARFOIS en
  suite (latérale port 119 m) selon l'ordre des tests — les sondes API
  directes H restent propres dans tous les scénarios mesurés.

## ✅ ITER147 (31/08, GO armateur) — MOTEUR I : écrêtage des routes officielles au TIRANT D'EAU + doublon « Les Errants »
- Ordre : « écrêtage des pointillés selon le tirant d'eau réel (cible banc du
  Turc), analyse d'abord le doublon Les Errants, ne touche QU'À engine_i.py ».
  Respecté : SEUL core/nav/engine_i.py modifié (+ test iter147).
- MOTEUR I (signalmar.i 7.0.0) = logique Moteur H (routes officielles
  prioritaires, faux couples corrigés, latérales > cardinales 1 km) MAIS :
  · réseau des pointillés construit PAR BESOIN D'EAU (tirant + marge − marée,
    plancher 0,5 m au ZH, cache par pas de 0,1 m — _network_i/_plan_tracks_i,
    copies gated de safe_routes qui reste INTACT pour H) ;
  · mesuré façade entière : ~20 km d'alignements à fond < 2 m conservés par
    H (clip 0,5) sont RETIRÉS chez I à besoin 2 m — ex. Passe Ouest Lorient
    (way 711666736, fond 0,65-1,96 m sur ~240 m) : 3878 → 3636 m ; Douarnenez
    718869417/420 ≈ 1,5 km chacun ; St-Malo 953941110 1,6 km. Banc du Turc
    (way 711666732) : le franchissement du banc était déjà exclu depuis le
    patch bathy iter145 (256 m profonds restants, identiques aux 2 clips) —
    la protection I est GÉNÉRALE (tout tirant, toute zone) ;
  · warning API : « … écrêtée à votre besoin d'eau (X m au zéro hydro) ».
- DOUBLON « LES ERRANTS » (analyse mesurée AVANT code, demande armateur) :
  2 latérales bâbord HOMONYMES à 351 m — tourelle BLANCHE id 1421434210
  (couleur white CONTREDIT la catégorie) + bouée ROUGE id 1421434206. En
  mode v6 leurs côtés requis divergent de ~82° (blanche→EST, rouge→NORD) =
  conflit réel : détour mesuré ~2× (1690 m vs ~900 m) pour contourner les
  deux, et risque de faux wrong_side/écrêtage contradictoire des pointillés.
  RÈGLE MOTEUR I : latérale de couleur EXPLICITEMENT contradictoire doublée
  d'une homonyme de couleur conforme à ≤ 600 m → plus AUCUNE règle de côté
  (écrêtage des pointillés + jonctions + audit final filtré) ; son écart
  minimal 60 m est conservé (jamais traversée). Couleur VIDE = inconnu OSM,
  jamais neutralisée (perches génériques de Douarnenez = faux positifs
  écartés). Seule la blanche est détectée sur toute la façade.
- ⚠️ LIMITE (périmètre engine_i.py) : le DÉTOUR du tracé causé par le
  demi-disque rasterisé de la blanche vient de seamarks.py (partagé A-H) —
  non corrigeable sans toucher ce fichier. Si l'armateur veut supprimer le
  détour : patch gated (contextvar armé par le Moteur I seul) dans
  seamarks.py, EN ATTENTE DE SON GO.
- FIX import circulaire : safe_routes → signalmar_v4 → algos/__init__ →
  engine_i ; tous les accès aux attributs de safe_routes différés dans les
  corps de fonctions (_MIN_CLIP_M littéral 0,5, _join_endpoints_i libre).
- Tests : tests/test_iter147_moteur_i_ecretage.py 6/6 (suspects, réseau
  écrêté, e2e API engine_i tracks+wrong_side vide, strip unit, gel H,
  mesure doublon) ; régressions : iter143 8/8, iter144 6/6, iter140/136
  14/14, iter137/139/133/îles 53 verts. AUCUN moteur A-H modifié.

## ✅ ITER143 (26/08, GO armateur) — MOTEUR H + fin du refactor map.tsx
- GO reçu : « Moteur H qui suit les routes officielles et corrige les faux
  couples » + « termine le découpage de map.tsx sans rien changer ».
- MOTEUR H (engine_h, algo signalmar.h, base Moteur F/v6, A-G INCHANGÉS) :
  - core/safe_routes.py : réseau des routes officielles (safe_routes.json,
    alignements écrêtés par bathy ≥0.5 m ZH, jonctions ≤300 m, composantes),
    plan_tracks(start,end,attach,bias) : sélection par composante sur le
    CORRIDOR (départ/milieu/arrivée + passe inversée côté arrivée), biais
    hors-piste 1.4 (un mètre hors pointillé coûte 1.4 m).
  - signalmar_h : legs raccord Moteur F + tronçons calés sur les pointillés,
    profil/audits recalculés sur le tracé assemblé, res.official_tracks +
    warning « Route calée sur la route officielle … ». Repli F intégral si
    aucun track. dir_coherence FORCÉ (corrige faux couples Jument 186°→6°,
    N°4 240°→60° — grâce à la grille 20 m). Params moteur ajustables sans
    UI : chenal_radius_m=1000, track_attach_m=3000, track_bias=1.4.
  - Règle latérales>cardinales : LATERAL_AUTHORITY_M (contextvar, 0=off,
    H=1 km) → sidefix saute le DÉTOUR de frôlement d'une cardinale flanquée
    d'une latérale fiable dans le rayon (l'audit continue d'avertir).
  - Seed engine_h dans manager._BUILTIN_SEEDS (parent engine_f).
  - RÉSULTATS : Lorient entrée engine_h = wrong_side VIDE (Jument+N°4
    corrigés), calé sur Passe Ouest/Sud + Ligne B, 1.6 s. Belle-Île→Arradon
    suit la Teignouse (18 km) + Port-Navalo + entrée Golfe. Connu/accepté :
    les tracks OSM passent PARFOIS sur la position exacte d'une balise
    (Grand Mouton à 0.1 m) → warnings « à vue » (l'armateur veut le calage
    EXACT sur le pointillé). tests/test_iter143_moteur_h.py = 8/8.
  - xfail (raison documentée) : iter139 e2e engine_f, iter139 n4 consensus,
    iter140::wrong_side_empty — faux couples corrigés par H, F gelé.
- REFACTOR map.tsx TERMINÉ : 4123 → 3730 lignes, déplacements PURS :
  modals/SearchByCodeModal, modals/MapFilterSheet, modals/ConeConfigModal,
  RouteBars.tsx (ManualRouteBar, RouteEditBar, RoutePickBar, PickPlaceBar) —
  tous sous src/screens/map/, styles partagés map-styles inchangés. Lint OK,
  erreurs tsc restantes = préexistantes (storage typings, theme.line…).

## ✅ ITER142 (26/08, ordre armateur) — MNT 20 m Lorient-Groix + routes sûres INGÉRÉS
- Ordre : « télécharge le MNT 20 m baie de Lorient→Groix, ingère (dont routes
  sûres), confirme, puis RIEN sans mon GO » (suite = Moteur H + fin refactor
  map.tsx, en attente du feu vert). Ville de Lorient exclue sur son ordre
  (« entrée → fin du port suffit »).
- SOURCE : aucun prépaquet SHOM 20 m ne couvre Lorient/Groix → LITTO3D BZH
  2018-2021 (lidar SHOM/IGN, Licence Ouverte), 20 paquets 5 km (~7 Go),
  MNT 5 m max-poolé (alt) → 20 m, mosaïque L93 → WGS84 0.0002°.
  scripts/ingest_litto3d_lorient.py (reprise Range + état litto3d_state.json,
  archives supprimées au fil de l'eau — disque limité).
- VERTICAL : Litto3D = IGN69 ≠ ZH → depth = z0 − alt, z0 = −2.34 m calibré
  par médiane vs TANDEM Morbihan (recouvrement Gâvres-Étel, n=76k,
  MAD=0.15 m). Conservateur (max-pooling ≈ +0.3 m pessimiste).
- LACUNES LIDAR (chenaux profonds/turbides sans retour, 72 % natif dans la
  rade seulement) : rebouchées par ATL100 partout où il répond, SAUF ≤ 2
  cellules d'une terre/assèche lidar. FAUX ASSÈCHES isolés (bords de bandes
  de vol, navires amarrés) : composantes ≤ 60 cellules avec ATL100 médian
  ≥ 5 m → remplacées (sinon murs NaN infranchissables — bug corrigé).
- PIÈGE (corrigé) : ingest_islands.py repart de *_orig.npy (idempotent) →
  TOUTE régénération de bathy_lorient.npy DOIT être suivie de
  `rm bathy_lorient_orig.npy` puis re-bake --zone lorient.
- Branché : core/bathy.py ZONE_FILES (morbihan > lorient > atl100 — TANDEM
  natif ZH prioritaire sur le recouvrement), ingest_islands.py ZONES,
  test_island_land_mask.py ZONE_MASKS. land_mask_lorient.npy (34 îles, 15
  nommées vérifiées, 0 échec).
- ROUTES SÛRES : scripts/ingest_safe_routes.py → data/bathy/safe_routes.json
  = 180 ways OSM façade entière (74 recommended_track, 90 navigation_line,
  16 fairway). AUCUN moteur ne les consomme encore (Moteur H, attente GO).
- CONTRÔLES : connectivité navigable large→passes→Jument→chenal→port→Groix
  = 1 seule composante ✓. Route test Lorient : atteint le port (8.8 km),
  fond mini 1.6 m (avant : −0.1 m « hauteur d'eau fausse » → RÉSOLU),
  dt≈3 s. PERF1/PERF2 iter140 repassent ✓ (< 10 s / < 5 s).
- ENV : contourpy manquait dans le pod forké (isobathes 500) → installé +
  requirements.txt. rasterio/py7zr/pyproj = deps scripts uniquement (hors
  requirements, politique existante).
- RESTE (exposé par la donnée fine, PAS des régressions de données) :
  ① wrong_side FAUX POSITIFS Jument + N°4 à Lorient : la route passe du BON
  côté (rouge à bâbord, vérifié géométriquement) mais l'inférence de
  direction est inversée par des FAUX COUPLES dos-à-dos (Jument rouge du
  chenal principal appariée à une verte du chenal secondaire à 106 m) →
  3 tests rouges (iter139 e2e, iter139 n4 consensus 0.4998<0.5,
  iter140::iter139_wrong_side). C'est le périmètre exact du Moteur H.
  ② iter103 home→côte start_blocked : PRÉ-EXISTANT (prouvé : identique avec
  et sans la zone lorient), indépendant de l'ingestion.
  ③ Échecs OTP/429 en suite complète séquentielle = artefact env connu.

## 🔍 ANALYSE 26/08 (post-fork) — captures armateur + Moteur H : AUCUN CODE, feu vert attendu
- Directive armateur : AUCUN CODE SANS AUTORISATION. map.tsx (fin du refactor)
  sera repris quand il donnera le feu vert, APRÈS cette analyse.
- Analyse complète livrée : /app/memory/ANALYSE_MOTEUR_H_2608.md
  (diagnostic des 6 captures « 26.08 post mihir », capacité de détection
  actuelle, faisabilité mesurée des routes officielles OSM, avis Moteur H).
- Faits mesurés clés : Lorient HORS zone pilote (MNT 20 m s'arrête à
  lng −3.333) → maille ~100 m ; le chenal de Lorient EST dans nos ATL100
  (6-18 m le long de l'axe) → « hauteur d'eau fausse » = placement de la
  route, pas la donnée. OSM contient recommended_track/navigation_line/
  fairway : Lorient 9 ways, Golfe 19, Quiberon 8, Loire 8, Brest 2,
  Douarnenez 0 (couverture inégale → repli calcul classique obligatoire).
  On n'ingère aujourd'hui QUE des nœuds balises (pas les ways).
- Avis rendu : Moteur H pertinent ; recommandé en « couloirs à coût quasi
  nul » dans l'A* (base F, gated) plutôt qu'en si/sinon ; rayon 1 km en
  param moteur ajustable par API sans UI. EN ATTENTE DE DÉCISION ARMATEUR.

## ✅ ITER127 (02/08, priorité armateur) — Erreurs 429 : calcul en tâche de fond + départ conservé, et fragilité du Moteur B corrigée
- **Plainte** : « 429 quasi à chaque calcul de route qui commence ou termine
  très près des côtes, entrées de ports… et à chaque fois le départ de la
  route saute ». La demi-solution précédente (2 ré-essais côté client) ne
  suffisait pas.
- **Diagnostic mesuré** :
  * un calcul côtier dure **10-20 s** (12,3 s Quiberon → Loire, mesuré) et
    **retenait une connexion HTTP** tout ce temps ;
  * pendant ce temps la WebView charge ses tuiles : **19 000 requêtes
    `/api/tiles/*` sur 20 500** dans les logs du jour. L'ingress de la
    plateforme plafonne les requêtes **simultanées par IP** → 429 sur le
    calcul lui-même ET sur `listReports` (d'où la fausse bascule
    « Hors-ligne — cache local » à chaque calcul) ;
  * le rate-limiter du backend n'est PAS en cause (aucun 429 sur
    `/routes/*` dans les logs serveur ; 300/min par IP jamais appliqué car
    pas de middleware SlowAPI).
- **Correctifs** :
  1. **CALCUL EN TÂCHE DE FOND** (le plus important) :
     `POST /api/routes/compute/async`, `…/manual/async`,
     `…/saved/{id}/recompute/async` rendent la main en **40 ms** avec un
     `job_id` ; l'app interroge `GET /api/routes/job/{job_id}` (réponses
     courtes). Un 429 sur une interrogation est **sans conséquence** : le
     calcul continue côté serveur et l'app récupère le résultat au coup
     suivant → le point de départ n'est plus jamais perdu. Job purgé à la
     lecture, TTL 15 min, 200 max.
  2. **PORTIER DE REQUÊTES** côté app (`src/api/client.ts`) : 3 requêtes en
     vol maximum, priorité aux calculs de route, 4 ré-essais
     (0,6/1,6/3,2/6 s) avec respect de `Retry-After`.
  3. **SILENCE RÉSEAU DE LA CARTE** pendant un calcul
     (`window.__setNetQuiet`) : préchargement de tuiles, ré-essais de tuiles,
     isobathes et balises sont mis en pause puis rattrapés.
  4. **Plus de fausse bascule hors-ligne** : un 429 sur `listReports`
     conserve l'affichage en cours (au lieu du cache 12 h + toast).
  5. **DÉPART CONSERVÉ** : en cas d'échec réseau (429/5xx/coupure), bandeau
     persistant « Calcul interrompu » avec **Réessayer** (mêmes départ et
     arrivée) et **Replacer le départ** (destination conservée).
  6. `nogil=True` sur le noyau A* numba : la boucle d'événements du backend
     (1 seul worker uvicorn) reste disponible pendant un calcul. Résultats
     numériques identiques (vérifié).
- **FRAGILITÉ MOTEUR B CORRIGÉE (sectionnement automatique)** :
  hors zone pilote la passe grossière agrège la bathy (maille 100 m, fond
  mini du bloc) et ce découpage dépend de la fenêtre, donc des points
  demandés : **déplacer l'arrivée de 77 m faisait passer de « Passage
  impossible » à une route de 84,4 km**. Le Moteur B (`signalmar.v2` 2.1.0)
  relance désormais le calcul en **2 tronçons de part et d'autre du point de
  blocage** annoncé par le moteur (`core/routing_engines/algos/signalmar_v2/
  stitch.py`) : cas de référence **83,97 km en 4,6 s** là où le Moteur A
  renonce en 3,5 s, avertissement explicite « Route calculée en 2 tronçons ».
  Garde-fous : tronçon mini 400 m, 1 seul re-découpage, refus si le total
  dépasse 3× la distance directe, sinon l'erreur d'origine est renvoyée.
- Tests : `tests/test_iter126_engine_b_standoff.py` **7/7** (dont
  reproduction de la fragilité sur A + sectionnement sur B),
  `tests/test_iter126_engines_api.py` 7/7. Suite complète : **630 passés**,
  8 échecs pré-existants (marée désactivée, seed démo, rate-limit).

## ✅ ITER126 (02/08, capture armateur 08:47 « Fernais 25 ») — Moteur B : écart minimal aux balises + ID des moteurs
- **Diagnostic (mesuré, scripts/diag_fernais.py)** : la route Loire → Golfe
  (R-20260802-064254-JH, 85,3 km, marge AUTO) passait à **4,7 m** de la
  bouée verte tribord « Fernais 25 ». 3 causes cumulées :
  1. `core/seamarks.py` **saute l'écart minimal (60 m) dès que la maille
     dépasse 45 m** (garde-fou du 28/07 : en maille grossière un disque de
     60 m scellerait des chenaux entiers) ;
  2. hors zone pilote (Golfe = MNT 20 m) la seule bathy est l'**ATL100** →
     maille réelle **75-110 m** dans les fenêtres de raffinement → l'écart
     minimal (et les murs de porte de chenal, et le côté strict) n'était
     **JAMAIS appliqué** sur toute la façade, Loire comprise ;
  3. en marge **AUTO** (plancher 10 m) l'érosion du masque est **nulle**
     (10 m ≪ maille) alors qu'en marge **MANUELLE 50 m** elle vaut 1 cellule
     (~75 m) → d'où l'écart 4,7 m (auto) vs 29,9 m (manuel 50) constaté par
     l'armateur. L'audit final détectait bien le frôlement mais se contentait
     d'un warning.
- **Correctif — nouvel algo `signalmar.v2` (Moteur B UNIQUEMENT ; Moteur A
  reste sur `signalmar.v1`, inchangé)** :
  `core/routing_engines/algos/signalmar_v2/standoff.py` — post-correction
  GÉOMÉTRIQUE (indépendante de la maille) : après le calcul complet du
  moteur historique, tout frôlement de balise est écarté à `écart
  recommandé + 10 m` en insérant un point de contournement du **côté déjà
  emprunté** (le balisage impose le côté). Chaque candidat est re-validé
  comme en passe 3 (fond ≥ seuil sur couloir ±15 m, murs de porte) et
  **scoré** : en présence d'une paire de bouées, le point visé est le
  **milieu du couloir** (sinon fuir une bouée rapprocherait de l'autre).
  S'il n'y a pas la place, le tracé historique est conservé avec son
  avertissement nominatif — aucune route n'est jamais perdue. Sécurité :
  fond mini jamais dégradé, sinon retour au tracé v1.
- **Mesures A/B** (scripts/diag_engine_ab.py) : Loire → Golfe marge AUTO —
  A : Fernais 25 à 4,7 m + MA 10,1 m + N°9 44,9 m ; B : **0 balise frôlée**,
  85,30 km (+10 m sur 85 km), fond mini identique 3,73 m. Marge manuelle
  50 m — A : 4 balises frôlées ; B : **0**, +140 m. Zone pilote (Morbihan,
  Vannes) : tracés **strictement identiques** A = B.
- **ID des moteurs (demande armateur)** : l'ID est désormais **indépendant
  du nom** — les duplications suivent la série `engine_c`, `engine_d`, … (fini
  les slugs dérivés du nom, qui devenaient faux après renommage). Affiché et
  copiable d'un tap dans Profil ▸ Navigation & routes (`ID : engine_b`) et sur
  la RouteCard (chip « Moteur B · engine_b ») → une route est traçable même
  après renommage du moteur.
- **Rebind built-in idempotent** : `manager.ensure_seed` met à jour l'algo
  (+ description) d'un moteur built-in quand le code le rebinde (engine_b →
  `signalmar.v2`). Les moteurs dupliqués par l'armateur ne sont jamais
  touchés. Les `params` du moteur sont désormais transmis à l'algo
  (`standoff_enforce`, `standoff_pad_m`, `standoff_max_detour_m`…).
- **A/B TESTING SUR LA CARTE (demande armateur du 02/08)** : le menu du tracé
  (tap sur la route) et la RouteCard proposent « Recalculer avec un autre
  moteur » → modale listant les moteurs **triés par ID décroissant** (le
  moteur de la route affichée est signalé et non sélectionnable) → recalcul
  → les **deux tracés restent affichés** : référence en fuchsia plein,
  variante en **ambre pointillé**, **portions divergentes surlignées**
  (halo épais, seuil 25 m) et **étiquette « moteur · ID » posée sur chaque
  tracé**. Barre de comparaison : distances, fond mini, nombre de zones de
  divergence, écart maxi, « Zoomer sur le plus grand écart », « Adopter la
  variante ». Fichiers : `src/lib/routeCompare.ts` (diff géométrique),
  `RouteCompareBar.tsx`, `EnginePickerModal.tsx`, `__setRouteCompare` dans
  `leaflet-html.ts`.
- **Fidélité du recalcul** : `SavedRouteIn` enregistre désormais les points
  **DEMANDÉS** (`start`/`end`) — les waypoints d'un tracé sont des nœuds de
  grille, repartir d'eux ne reproduit pas le calcul (sensibilité de la passe
  grossière : un décalage de 60 m sur l'arrivée suffisait à faire échouer le
  recalcul). Le repli de marge latérale du recalcul passe de 150 m à la
  **marge AUTO** (l'ancien repli déclenchait « départ dans une zone non
  navigable » sur les routes prises au ponton).
- Tests : `tests/test_iter126_engine_b_standoff.py` 5/5 +
  `tests/test_iter126_engines_api.py` 7/7 (API : engines, A vs B, saved +
  recompute, non-régression zone pilote, duplicate → `engine_c`, rename sans
  changement d'ID). Suite complète : 623 passés, 8 échecs **pré-existants**
  (marée volontairement désactivée, seed démo 26/30, rate-limit) — aucun lié
  au routage A/B.
- **NOUVELLE URL PRÉVIEW (fork 02/08) : marine-nav-refactor.preview.emergentagent.com**

## ✅ ITER117 (27/07, analyse vidéo armateur 09:17) — 6 correctifs route
- **Parcs de culture marine JAMAIS traversés** (vidéo 04:18, nord de Drenec) :
  scripts/ingest_marine_farms.py (OSM seamark:type=marine_farm +
  landuse=aquaculture → data/bathy/marine_farms.json, 979 polygones façade
  atl100 dont 235 Morbihan, 29 459 disques). core/seamarks.py : _farm_cover
  (semis de disques r 60 m / pas 70 m) rasterisé dans `blocked` SANS AUCUNE
  exemption (ni marée, ni MOORINGS_OPEN, ni départ/arrivée) + ajouté aux
  clearance_points (le redressement ne coupe jamais un parc).
- **Marée à H+30 min** (consigne armateur 05:44) : TIDE_LEAD_S=1800 dans
  routers/routing.py — la hauteur utilisée est celle PRÉVUE 30 min après le
  calcul (le bateau n'est pas sur zone avant). Warning + RouteCard adaptés
  (« Marée prévue à HH:MM (calcul +30 min) »).
- **Balise No8 (vidéo 03:39)** : la route passait DESSUS parce que l'arrivée
  DÉPLACÉE tombait à < 200 m de la balise → exemption d'écart minimal levée
  à tort. Fix : strict_exempt = (départ, arrivée DEMANDÉE orig_end), jamais
  une arrivée relogée par le moteur. Mesuré : No8 à 35 m, No6 28 m.
- **Arrivée déplacée jamais sur la vasière** (vidéo 07:23, ÉCHEC TOTAL) :
  nearest_reachable préfère (1) un point navigable SANS marée (fond ≥
  tirant+marge au ZH) s'il est ≤ +2,5 km du plus proche (retest : +800 m
  ratait le pool de La Marle à grande marée) ; sinon (2) le point le plus
  PROFOND ≤ +400 m (thalweg du chenal). Vannes : arrivée pool de La
  Marle fond 1.68 m ZH (= l'endroit du drapeau « bon » de 09:19).
- **« Aucune route plus sûre » sur la RouteCard** (vidéo 05:20) : le message
  d'échec est ajouté aux warnings de la route conservée + affiché dans le
  popup 150 % (safer-fail-msg) — plus seulement un toast en haut.
- **429 ingress** (vidéo 02:42) : POST /routes/compute et /routes/manual
  réessayés 2× avec backoff (client.ts) comme les GET.
- Tests : tests/test_iter117_farms_tide30_arrival.py 5/5 ; régressions
  iter93→116 : 100 pytest verts (iter115 : assertion warning adaptée).
- **NOUVELLE URL PRÉVIEW (fork 27/07) : prochaine-maree.preview.emergentagent.com**
- Explications armateur (pas de code) : 02:35 = seuils du chenal < besoin
  même à +2 m (plancher −2,5 m ZH) → troncature au dernier point sain ;
  05:07 = 1,7 m ≥ besoin 1,5 m mais < 150 % (2,25 m) d'où l'alerte ;
  balises raster qui disparaissent = tuiles OpenSeaMap manquantes à certains
  zooms (cache serveur ne peut servir que ce que l'amont fournit) — résolu
  définitivement par cartes locales embarquées (feature offline à venir).

## ✅ ITER116 (27/07, GO armateur) — PROCHAINE MARÉE SUFFISANTE sur la RouteCard
- core/tides.py : tide_crossings(lat,lng,start,need,24h) → now_ok /
  next_ok_ts / ok_until_ts / max_m (pleine mer max) au port le plus proche,
  pas de 10 min sur la série Open-Meteo.
- routers/routing.py (3 cas) :
  a) route passable UNIQUEMENT grâce à la marée (min_depth < tirant+marge) →
     result.tide_window {required_m, ok_until_ts, port} ;
  b) arrivée déplacée > 800 m → calcul HYPOTHÉTIQUE à la pleine mer des 24 h
     (réglages DERNIER RECOURS : MOORINGS_OPEN + marge 10 — sinon le balisage
     faussait la conclusion) → result.tide_better {ts, required_m, offset_m}
     + warning « ira PLUS LOIN à partir de ~HH:MM » ; sinon warning « même à
     pleine mer, l'arrivée resterait déplacée » ;
  c) REFUS (422 no_route/start/end_blocked + use_tide) → même hypothèse →
     detail.tide_retry {next_ok_ts, required_m, port} + message « ✅ AVEC LA
     MARÉE, ce trajet devrait passer À PARTIR DE ~HH:MM … recalculez ».
  _fmt_local (Europe/Paris, « demain » / « le JJ/MM »).
- RouteCard.tsx : lignes route-tide-window (orange, « Passable tant que la
  marée ≥ +X m — jusqu'à ~HH:MM ») et route-tide-better (vert, « Ira plus
  loin … actualisez la route ») ; fmtTideTs. Types client.ts tide_window/
  tide_better. Le message d'échec (tide_retry) passe par detail.message.
- Vérifié en réel (Vilaine) : PM → tide_window required 2.23 jusqu'à ~HH:MM ;
  mi-marée 1.85 → tide_better « ~0,7 km au lieu de ~4,2 km à partir de 18:00
  demain » ; BM → 422 + « devrait passer à partir de ~18:00 demain (≥ +2,6 m) ».
  56 pytest verts (iter96→115, iter115 étendu avec assertion tide_window).


## ✅ ITER115 (26/07 soir, décision armateur) — MARÉE À L'INSTANT T + « Actualiser la route »
### Fixes moteur supplémentaires trouvés en reproduisant « Foireuse 3 » (tous testés, 92 pytest verts)
- **Cause n°1 (balisage !)** : sens conventionnel FAUX dans la Vilaine (champ
  pilote orienté N au lieu d'E) → demi-disques latéraux (No9→No21) EN TRAVERS
  du chenal = coupure à chaque bouée. Fix : en DERNIER RECOURS (MOORINGS_OPEN)
  les règles de CÔTÉ latéral sont levées (seamarks.py) — profondeur, dangers,
  cardinales conservés — avec warning explicite « vérifiez le balisage À VUE ».
  Généralisation propre du champ = Lot 2b (V2).
- routers/routing.py : le dernier recours est AUSSI tenté quand un palier
  réussit avec arrivée déplacée > 800 m, préféré s'il gagne > 500 m
  (factorisation _last_resort()).
- core/routing.py : nearest_reachable VALIDÉ pleine résolution (la fenêtre
  poolée renvoyait un point À TERRE → no_route sec) ; plafond de troncature
  « arrivée déplacée » adaptatif _trunc_cap_m (max(5 km, 15 % du trajet),
  borné 12 km — le blocage à 5,16 km était refusé pour 160 m) ; pénalité A*
  sur cellules découvrantes (dry_pen, l'A* reste dans le vrai chenal à marée
  haute) ; retry unique « marge renforcée +0,5 m » si le contrôle final
  pleine résolution refuse (raccourci de décimation sur vasière).
- Résultat mesuré : Arradon → Foireuse (barrage d'Arzal) à marée +2,2 m au
  calcul → arrivée à 1 017 m de la destination (le reliquat = plan d'eau du
  barrage +4,3 m ZH, infranchissable par les données + écluse) contre
  3 640-5 160 m avant. Test : tests/test_iter115_vilaine_instant_tide.py.

- **DÉCISION V2 (mémorisée)** : la « marée à l'heure de PASSAGE par tronçon »
  (ETA par cellule, 2 ports mélangés, fenêtres horaires de départ) est un
  chantier TROP GROS → reporté V2. Analyse complète du 26/07 (cas « Foireuse
  3 ») : le chenal Tréhiguier→barrage d'Arzal a des seuils ~0/+0,3 m ZH ;
  l'ancienne règle (marée MINIMALE sur la fenêtre 7-9 h, port du DÉPART)
  coupait la route à -2.424 alors que la marée à l'heure d'arrivée réelle
  (+2,5 m à 00h20) permettait le passage. Amont de -2.382 = plan d'eau du
  barrage (+4,3 m ZH) : jamais franchissable (écluse), normal.
- **Nouveau comportement (routers/routing.py)** : tide_m = hauteur AU MOMENT
  DU CALCUL (height_start_m, port le plus proche du départ) ; le mini de la
  fenêtre reste INFORMATIF. Warning systématique ajouté à chaque route avec
  marée : « hauteur relevée au moment du calcul… vérifiez à votre heure de
  passage, actualisez la route avant les passages sensibles ».
- core/routing.py : texte « UNIQUEMENT grâce à la marée » adapté (re-vérifiez
  / actualisez au lieu de « ne différez pas le départ »).
- **Frontend** : RouteCard — ligne marée « au moment du calcul (HH:MM) : +X m
  · PORT — mini ~+Y m sur Z h : vérifiez à votre heure de passage » ; bande
  rouge basée sur height_start_m. map.tsx — routeCtxRef (dest/from de la
  dernière route auto) + entrée menu tracé « Actualiser la route »
  (route-menu-refresh, visible route auto seulement) = recalcul immédiat
  avec la marée de maintenant.
- **Backups vérifiés (preuve à l'armateur)** : mongo_20260726_1007.tar.gz
  restauré réellement dans une base temporaire → 15 748 docs, 0 échec,
  comptages cohérents (535 users…) ; pas de backup daté 25/07 (dernier avant
  fork = 26/07 10h07 ; « Foireuse 3 » créée à 17h57 n'y est pas → nouveau
  backup à refaire après ce lot).


## ✅ ITER114 (26/07 post-fork) — « logs/vidéos cassés » : FAUSSE PANNE + envoi de captures d'écran
- L'armateur pensait l'envoi logs/enregistrements CASSÉ. VÉRIFIÉ EN BASE : tout
  est ARRIVÉ le 26/07 (3 bundles diagnostics 12h09/15h11/15h12 + vidéo 2,3 Mo
  15h13, fichier dans uploads/support/). L'agent précédent n'avait pas re-vérifié.
- ANALYSE des logs reçus : « Cannot connect to Metro » répétés + 429/404 vers
  l'ANCIENNE URL (tides-anchor-test.preview…). L'app de l'armateur (Expo Go,
  Samsung SM-T733 Android 14) pointait sur l'ancien environnement pré-fork →
  crashs écran noir quand Expo Go perd Metro (ex: passage en arrière-plan pour
  capture d'écran + mail). CE N'EST PAS UN BUG DU CODE. Action armateur :
  ROUVRIR l'app via la nouvelle URL safesea-nav.preview.emergentagent.com.
- ANALYSE vidéo reçue : carte non rendue (fond bleu) → flicker → écran noir 2×,
  onglets Météo/Détresse/Sécurité OK entre les crashs — cohérent avec la perte
  Metro de l'ancien env, pas une régression app.
- AJOUTÉ : bouton « Envoyer des captures d'écran (max 5) » (diag-send-screenshot,
  multi-sélection images, upload chunké séquentiel, progression globale) via
  pickAndSendSupportScreenshots dans src/lib/support-upload.ts (refactor
  sendAssetToSupport partagé) + RETRY 1× automatique par chunk (sendChunk).
- Testé : flux init/chunk/complete 200 e2e sur la nouvelle URL (JWT admin),
  écran /diagnostic rendu OK avec les 2 boutons.


## 🚧 EXTENSION DE ZONE FRANCE-OUEST + LOT SUPERVISEUR ÎLES (23/07/2026, GO armateur)
### Lot 1 — consigne superviseur (îles/tests) ✅
- Cause racine du faux « décalage 200 m » : la projection WGS84→grille était
  CORRECTE (écart OSM↔masque mesuré 20-35 m = quantification 20 m) ; les
  coordonnées de CONTRÔLE codées en dur étaient fausses (point en mer). Même
  erreur retrouvée dans MA liste pytest (Dumet à 330 m) → d'où la règle :
  points intérieurs vérifiés OSM uniquement.
- scripts/ingest_islands.py v2 : générique par zone (--zone morbihan|atl100,
  emprise dérivée du meta de la grille), Overpass en tuiles ≤1.2°,
  AUTO-VÉRIFICATION post-rasterisation (point intérieur par ray-casting — la
  moyenne des sommets tombe en mer pour les îles concaves type Île-aux-Moines),
  rapport land_mask_{zone}_report.json, exit 1 si une île > 200 m échoue.
  Morbihan ré-ingéré : 123 îles nommées, 0 échec.
- tests/test_island_land_mask.py : 15 îles de référence (8 pilote + 7 zone
  étendue auto-activées), vérif masque + depth_at + routes tentées AU TRAVERS
  (Er Lannic, Arz, Houat, Groix, Belle-Île, Yeu) échantillonnées 10 m → 0
  cellule terre. À exécuter avant toute livraison.
### Lot 2a — zone étendue Manche Ouest → Pertuis (capture armateur)
- MNT HOMONIM façade Atlantique 100 m (SHOM public, 464 Mo .7z) ingéré via
  scripts/ingest_shom_atl100.py, crop 45.7→49.0 / -5.45→-1.0 (3300×4450,
  bathy_atl100.npy 59 Mo). URL vérifiée dans le script.
- core/bathy.py multi-zones : ZONE_FILES (fine→grossière), MosaicGrid
  (depth_at/sample = la plus fine qui couvre GAGNE, ses NaN jamais rebouchés ;
  window = fine si bbox contenue (fast path pilote inchangé), sinon base
  grossière + OVERLAY fine max-poolée au pas de la maille — l'ATL100 a des
  TROUS côtiers : entrée du Golfe, ports), get_zone_grid(name) pour les
  seamarks (champ conventionnel = zone pilote).
- Moteur (core/routing.py) durci pour données 100 m :
  · érosion marge latérale seulement si marge ≥ maille (l'ancien min 1 cellule
    scellait les détroits à 200-700 m) ;
  · A* SANS coupe de coin en diagonale (voisins orthogonaux navigables) ;
  · réparation : fusion des tronçons consécutifs dangereux (plateaux type
    Penmarc'h), fenêtres pad 0.008→0.25° (dogleg Raz de Sein), px adapté pour
    step 1, candidats RE-VALIDÉS (récursif 1 niveau) + jointure a→snap(a)
    contrôlée, sinon meilleur candidat par profondeur ;
  · REFUS FERME si profil final < seuil-0.45 (bande warning en dessous) —
    plus de « warning » à -1 m ;
  · pénalité proximité danger ∝ maille (d0 ≥ 2×cellule) ;
  · _corridor_safe/centerline pas 15 m en zone 20 m, 40 m ailleurs ;
    _straighten raccourcis bornés 30 km (perf routes 200+ km) ;
  · extrémités traitées AVANT réparation ; helper nearest_navigable().
- Fallback testeur : départ à terre → eau navigable la plus proche (≤5 km),
  sinon Arradon (chaîne 2e/3e chance, routers/routing.py).
- Marées : +20 ports façade Ouest (calibration générique, disclaimer).
- Routes validées : Lorient→Brest (Raz de Sein ✅ 3.16 m min), Brest→StMalo
  (260 km, 11 s), Quiberon→Yeu, Arradon→La Rochelle (2.27 m min), Roscoff,
  Ouessant + régressions pilote 0.4-0.5 s inchangées. Pytest iter93-102 +
  îles : verts (3 tests mis à jour pour comportements volontaires).
### ⏳ Reste (Lot 2b/2c) — limitations CONNUES zone étendue
- Balisage IALA + dangers OSM (roches/épaves cliquables) = ZONE PILOTE
  UNIQUEMENT ; hors Morbihan les routes ne s'appuient que sur la bathy 100 m.
  → ingest_seamarks/hazards étendus + généralisation du champ « sens
  conventionnel » (graines = bord océan profond, plus S+O pilote).
- Marées hors zone pilote : calage générique (± précision), pas de
  calibration par port.
- ingest_islands --zone atl100 : Overpass surchargé (504/429) — à relancer
  si échec ; en attendant les îles ATL100 = nodata produit (déjà surs à ~95 %).
- Résolution 100 m hors Morbihan : chenaux < ~200 m, rivières et bassins
  portuaires approximatifs/fermés à ZH (conservateur assumé).

## ✅ BUG ARMATEUR 23/07 (post-fork) — « Passage impossible » route auto, départ à terre (iter102 ✅ 51/51)
- Reproduit : croix de DÉPART posée à terre (Locmariaquer 47.57,-2.94) → le
  snap (400 m) accrochait une POCHE d'eau isolée du MNT → A* sans issue →
  422 `no_route` « Passage impossible » → le fallback Arradon des testeurs
  (déclenché uniquement sur `start_blocked`) ne partait JAMAIS.
- Fix core/routing.py : `TRAP_POCKET_KM2 = 1.0` + `trap_check=True` en
  passe 1 UNIQUEMENT — sur échec A*, composante d'eau du départ/arrivée
  < 1 km² → `_SnapFail` → start_blocked/end_blocked (le fallback Arradon
  testeur se déclenche ; compte normal = message clair « Départ dans une
  zone non navigable… »). PAS appliqué aux fenêtres fines (elles peuvent
  couper une composante réellement connectée).
- AUDIT COMPLET du lot 22-23/07 demandé par l'armateur : 60/60 pytest
  iter93-101 AVANT fix (le lot était intact), 45/45 après, + balayage 26
  routes réalistes (Belle-Île, Houat, Hoedic, Teignouse, Crouesty…) — seuls
  échecs restants = conservatisme ZH attendu (chenal de Vannes, rivière
  d'Auray, bassins qui découvrent) documenté depuis iter93.
- Verrou : tests/test_iter102_trap_pocket_armateur_bug.py (6 tests, agent).
- ⚠️ Échecs de la suite pytest COMPLÈTE (21 failed/17 errors) = tests
  OBSOLÈTES pré-lot (alert_test_batch 0.2→0.6 km, switcher ouvert-à-tous
  → restreint iter90, fixtures expirées iter59/demo seed…) — PAS des
  régressions ; nettoyage à planifier.

## ✅ LOT BALISAGE IALA + FENÊTRE ROUTE (21/07/2026, GO armateur — iter96 : 17/17 pytest + frontend PASS)
- **Règle assimilée (validée par l'armateur)** : sens conventionnel = du
  LARGE vers l'ABRI (port/côte/remontée de fleuve). Chaque latérale se
  suffit : « verte à tribord en entrant » = « verte à bâbord en sortant » =
  LE MÊME côté absolu → demi-disque interdit FIXE par balise, valable dans
  les 2 sens. JAMAIS traiter une latérale en danger isolé.
- **Ingestion balisage** : `scripts/ingest_seamarks.py` (Overpass OSM, UA
  requis, retry 504) → data/bathy/seamarks.json : 387 balises zone pilote
  (204 latérales — 7 sans côté NI couleur → ignorées ; 104 cardinales ;
  19 dangers isolés ; 60 spéciales). Côté déduit de la couleur si catégorie
  absente. Relancer le script pour rafraîchir.
- **`core/seamarks.py`** : champ « distance au large » (BFS géodésique à
  travers l'eau sur grille décimée ×8, graines = bords SUD+OUEST seulement
  — l'est=Vilaine et le nord=terres contaminaient le champ ; terre remplie
  par la valeur d'eau la plus proche AVANT lissage gaussien σ=4, sinon le
  gradient pointe vers la terre) → conventional_dir(lat,lng). Rasterisation
  des interdits : latérale demi-disque 60 m (cross produit vs direction
  conventionnelle), cardinale demi-plan côté danger 120 m, danger isolé
  disque 80 m (A* contourne au plus court), spéciale 40 m, safe_water rien.
  Vérifié : entrée du Golfe dir=Nord, Grand Mouton NNE, rivière d'Auray NNO.
- **core/routing.py** : contraintes appliquées APRÈS la dilatation de marge
  (pas de double marge) + **ARRONDI des virages** `_round_corners` (coupe
  d'angle 30 % ×2 itérations, chaque raccourci re-validé par ligne de vue
  sur le masque — jamais d'arrondi qui coupe un danger) ; waypoints en
  cellules flottantes interpolées. Tolérance tests : min_depth ≥ seuil−0.25 m
  (arrondi validé sur masque décimé ~30 m vs grille 20 m ; couvert par la
  marge utilisateur + warning API).
- **Fenêtre route (bug armateur corrigé)** : RouteCard a chevron-down
  (route-minimize → mini-pill route-min-pill distance) + ✕ (route-close =
  MASQUE seulement, la route reste). Suppression = TAP SUR LE TRACÉ
  (polyline invisible 18 px interactive → event route_tap → menu
  route-menu-details / route-menu-delete). setRoute(null) UNIQUEMENT là.
- Reporté (plan armateur) : clic long sur la route = créer/déplacer un
  waypoint • bouton « Démarrer la navigation » • halo gris du corridor •
  balises cliquables (fiche info) — les données sont déjà ingérées.
- L'armateur va « jouer » avec des routes complètes et remonter les passages
  incorrects → prévoir table d'exceptions par balise si besoin.

## ✅ BYPASS TEST ROUTAGE (20/07/2026 soir, demande armateur — iter95 ✅ 4/4 pytest)
- routers/routing.py : pour les COMPTES DE TEST (is_beta_tester = dev/admin +
  beta_testers), si le DÉPART est hors zone pilote (out_of_coverage) ou à
  terre (start_blocked) → remplacé par ARRADON (47.610, -2.825 — large
  d'Arradon, 4.8 m ZH, centre du Golfe). Warning inséré dans la RouteCard :
  « Mode test : départ hors zone → remplacé par Arradon… ». JAMAIS pour la
  destination, JAMAIS pour les comptes normaux (422 inchangé — testé).
- L'armateur (dans les terres) peut donc tester « Naviguer ici » ET « Créer
  une route » depuis chez lui.

## ✅ LOT 20/07/2026 (après-midi) — Réglages accordéons + écart de route + marées + menu 3 choix (iter94 ✅)
- **Réglages en ACCORDÉONS** (choix armateur : option a) — `AccordionSection.tsx`,
  4 familles dans app/profile/settings.tsx (une seule ouverte, « veille » par
  défaut, deep-link focus=autoswitch conservé) : 👁 Zones de veille & alertes
  (AlertSettingsPanel full) / 🧭 Navigation & routes (RouteGuardPanel) /
  ⛵ Mon bateau (lien /profile/boat) / 👤 Compte & application (pseudo,
  abonnement, diagnostic, comptes de test). Partage + déconnexion en fin.
- **Alerte d'ÉCART DE ROUTE** — `src/lib/route-guard.ts` : toggle (défaut ON)
  + seuil 5-200 m (défaut 50) persistés sm.route.guard_on/_threshold_m ;
  distanceToRouteM (point→segments équirect). Runtime dans map.tsx : à chaque
  tick GPS si route active + option ON + vitesse ≥ 0,8 m/s → sortie corridor
  = vibrateAlert + playRouteDeviationSound + toast, rappel 30 s, retour
  < 80 % du seuil = réarmement + toast succès. **SON DÉDIÉ EN ATTENTE** :
  placeholder ROUTE_DEVIATION_ASSET=null dans alert-sound.ts — quand
  l'armateur fournit le fichier, le mettre dans assets/sounds/ et remplacer
  par require(...). DIFFÉRENT des sons de signalement (règle armateur).
- **MARÉES (Open-Meteo approché — choix armateur, API SHOM SPM payante
  ~200 €/an refusée pour l'instant)** — `core/tides.py` + GET
  /api/tides/nearest?lat&lng (public) : 26 ports embarqués Bretagne Sud,
  extrema BM/PM (parabole sur série horaire sea_level_height_msl),
  COEFFICIENT approché = marnage Brest simultané/(2×3.05)×100 (clamp 20-120),
  hauteurs ≈ZH via extrapolation coef 120, cache 6 h/port. UI :
  `TideCard.tsx` dans l'onglet Météo (chips 3 ports + 5 jours, badges coef,
  disclaimer non officiel). 4/4 pytest (test_iter94_tides.py). V2.1 : brancher
  la marée dans le calcul de route (fenêtres horaires chenal de Vannes).
- **Menu appui long 3 CHOIX** : Signaler ici / Naviguer ici (depuis bateau) /
  **Créer une route** (testID longpress-create-route) → destination mémorisée,
  croix + carte LIBRE pour placer le DÉPART, barre route-pick-bar
  (Annuler / Calculer la route) → computeSafeRoute(dest, départChoisi).
  Utile hors zone pilote pour préparer/tester des itinéraires.
- **Auto-recentrage suspendu à l'appui long** (SM.setFollowSuspended dans
  leaflet-html + handle suspendFollow) — réactivé UNIQUEMENT par le bouton
  de recentrage (locateMe → suspendFollow(false)).
- Fix affichage RouteCard (iter94) : légende sortie du conteneur
  overflow:hidden, Svg en largeur MESURÉE (width:"100%" bugué en RN-web),
  routeCardWrap right:72 pour ne pas passer sous la colonne de boutons.
- ⚠️ Erreurs tsc PRÉ-EXISTANTES inchangées (support-upload, ProximityConfirmCard…).

## ✅ V2 PHASE N1 — Isobathes + moteur de route sûre (20/07/2026, iter93 ✅ 10/10 pytest + frontend validé)
- Demande armateur (vidéo Navionics) : isobathes selon le zoom, profil bateau
  complété, surbrillance des zones < tirant + marge, puis GO N1.
- **Ingestion MNT SHOM** : `scripts/ingest_shom_mnt.py` télécharge le prépaquet
  MNT_COTIER_MORBIHAN_TANDEM_20m_PBMA (.7z 105 Mo, URL publique
  services.data.shom.fr/INSPIRE/telechargement/prepackageGroup/…) → grille
  `data/bathy/bathy_morbihan.npy` (float32 memmap 51 Mo, 2626×4834 à 20 m,
  PROFONDEUR sous ZH positive, NaN=hors produit) + meta json. Sources
  nettoyées après conversion. Emprise : -3.333→-2.367 / 47.20→47.725.
  Libs ajoutées : rasterio, py7zr, scipy, contourpy (requirements.txt à jour).
- **`core/bathy.py`** : BathyGrid (memmap, depth_at, window décimée) +
  isobaths_geojson via contourpy. Niveaux PAR ZOOM (z≤9: 20/50 … z≥15:
  1/2/3/4/5/7/10/15/20/30/50) — AUCUNE couche isobathes dans le WMS SHOM,
  on les génère nous-mêmes.
- **`routers/bathy.py`** (public) : GET /api/bathy/isobaths?bbox=w,s,e,n&z=
  → FeatureCollection LineString {depth} + levels ; GET /api/bathy/coverage.
  Garde-fou bbox > 2.5° → vide.
- **`core/routing.py`** : moteur A* — fenêtre décimée (MAX_DIM 520, pad 35 %
  min 0.05°), masque profondeur ≥ tirant+marge (NaN interdit), dilatation
  elliptique = marge latérale, distance_transform_edt → pénalité de proximité
  (préfère le milieu du chenal, PENALTY_K 0.6), A* 8-connexe heapq, lissage
  ligne de vue, snap départ/arrivée ≤ 400 m (extrémités REMPLACÉES par le
  point accroché si point brut à terre — bug corrigé), profil de profondeur
  100 m (avec lat/lng) sur grille pleine résolution. Erreurs typées :
  out_of_coverage / start_blocked / end_blocked / no_route (messages FR).
  Perfs mesurées : 0.03-0.34 s. Chenal de Vannes refusé à ZH = conservateur
  attendu (V2.0 sans marée).
- **`routers/routing.py`** : POST /api/routes/compute (auth, asyncio.to_thread,
  bornes serveur = mêmes que le profil bateau).
- **Frontend** :
  · MarineMap/leaflet-html : `__setIsobaths(on, baseUrl)` (fetch DANS la
    WebView, debounce 350 ms moveend/zoomend, seq anti-race, ≤60 libellés
    .sm-iso-label halo blanc, lignes majeures 5/10/20/50 plus marquées,
    liées au MÊME bouton goutte d'eau que la bathy WMS) ; `__setRoute(route)`
    (liseré blanc + rouge pointillé, segments ORANGE si profondeur <
    seuil+0.5 m via depth_profile lat/lng, rond vert départ + drapeau 🏁,
    fitBounds seulement quand la route change — pas au ré-émis 'ready').
  · client.ts : api.computeRoute + types ComputedRoute ; extraction de
    detail.message des erreurs objet (RouteError).
  · map.tsx : « Naviguer ici » → getBoatSettings + computeRoute depuis la
    position GPS (toast erreur si pas de GPS), pill « Calcul de la route
    sûre… », RouteCard (src/components/RouteCard.tsx) : distance km+NM,
    graphe SVG du profil (react-native-svg, seuil rouge pointillé, fond
    mini), warnings, disclaimer SHOM, bouton fermer (zIndex 2 — fix iter93).
  · Profil bateau COMPLÉTÉ (ordre armateur) : Tirant d'eau 1.5 / Marge
    profondeur 0.5 (0-3) / Tirant d'air 3 (0.5-35) / Marge hauteur 1 (0-3) /
    Marge latérale 50 (50-500) — clamps + persistance validés iter93.
    Tirant d'air + marge hauteur STOCKÉS mais pas encore utilisés (ponts =
    données à intégrer plus tard).
- Tests : `tests/test_iter93_routing_bathy.py` 10/10 ; testing agent iter93 :
  tous flux frontend PASS (5 champs bateau, isobathes 347 paths + 60 labels,
  route 4 km affichée + RouteCard, régressions OK).
- 🔜 N2 : édition waypoints (tap/drag + re-validation), override « danger
  assumé » consenti, signalements SignalMar dans le corridor + alertes en
  route, surbrillance CARTE des zones < tirant+marge (hors route), CGU.
- ⚠️ OTP rate-limit en test UI : 5 SMS/h/numéro — utiliser Aslak 0766071445
  si l'admin est épuisé (header QA X-RateLimit-Bypass en API).

## ✅ V2 PHASE N0 — Préparation (20/07/2026, GO armateur, self-testé e2e ✅)
- Décisions armateur ACTÉES : zone pilote = Golfe du Morbihan/Bretagne Sud ;
  V2.0 SANS marée (profondeurs conservatrices ZH, marée en V2.1) ; GO N0.
- **Refactor iso-fonctionnel (dette bloquante)** :
  · MarineMap.tsx 1957 → 367 l. — buildHtml + TYPE_COLOR (1590 l. de HTML/JS
    Leaflet) extraits en DÉPLACEMENT PUR vers
    `src/components/marine-map/leaflet-html.ts`.
  · map.tsx 2794 → ~2300 l. — styles (614 l.) extraits vers
    `src/screens/map/map-styles.ts`. Aucune régression (carte, marqueurs,
    bathy, mode Nav vérifiés e2e web ; seules les 3 erreurs tsc
    pré-existantes subsistent).
- **Curseur d'opacité bathy TEMPS RÉEL** (remplace les chips 30/50/70/100) :
  MarineSlider 30-100 % pas 5, testID bathy-opacity-slider +
  bathy-opacity-value ; chaque tick → prop bathymetryOpacity →
  window.__setBathyOpacity (aperçu live vérifié 70→40 %). Persistance
  sm.map.bathy_opacity inchangée.
- **Menu appui long 2 choix** (testIDs longpress-report / longpress-navigate) :
  popup « Position choisie » (coords DM) → « Signaler ici » (flux V1 intact,
  /report/new?lat&lng&src=longpress) / « Naviguer ici » → toast « bientôt (V2) »
  — sera branché sur le moteur de route en N1.
- **Réglages bateau** : Profil → tuile « Mon bateau » (profile-open-boat) →
  `/profile/boat` (app/profile/boat.tsx). Tirant d'eau 0.2-4 m (défaut 1.5)
  + marge latérale 50-500 m (défaut 50, minimum 50 IMPOSÉ par clamp).
  Slider + saisie directe, persistés sm.boat.draft_m / sm.boat.margin_m via
  `src/lib/boat-settings.ts` (hook useBoatSettings + getBoatSettings() async
  pour le moteur N1). Vérifié e2e : défauts, 2.3 OK, 30→50, 900→500, persistance.
- 🔜 SUITE = **N1 moteur de route** : ingestion MNT SHOM (Morbihan 20 m +
  ATL 100 m) côté serveur, masque navigable + A* + lissage,
  POST /api/routes/compute, affichage route — voir V2_NAVIGATION_ANALYSE.md.

## FIX scintillement radar (20/07/2026, vidéo armateur, iter91 ✅ 100 %)
- Symptôme : anneaux du radar Vigie clignotant par à-coups après une alerte
  (corne + vibrations) et au retour de l'écran notifications (Android).
- Root cause : animation JS (requestAnimationFrame + setRadius/setStyle par
  frame sur cercles SVG) → frames sautées dès que le thread WebView charge.
- Fix MarineMap.tsx : animation 100 % CSS (@keyframes smPing, scale
  0.02→1 + stroke-opacity .9→0, transform-box:fill-box, anneau B décalé
  -1.6 s via .sm-radar-b), rayon Leaflet FIXE = zone de veille, pingRaf
  supprimé. iter91 : 22 échantillons/4,2 s SOUS ALERTE ACTIVE = onde
  monotone sans saut ; régressions toggle/zoom/suivi bateau/alerte OK.
- Réception des logs diagnostic VÉRIFIÉE : bundle armateur du 20/07 09:17
  bien en base (db.diagnostics, 35 bundles) — GET /api/diagnostics/ping ok.

## MODE TEST BÊTA V1 (19-20/07/2026, GO armateur, iter90 ✅ 19/19 pytest)
- Préparation distribution APK : les bêta-testeurs déclarés créent des
  signalements de TEST depuis la terre (badge TEST carte + fiche), les
  valident/invalident entre leurs comptes, bascule rapide restreinte.
- Backend `routers/beta.py` : collection beta_testers (admin CRUD
  /api/beta/testers, normalisation 06→+33), /api/beta/status,
  /api/beta/test-mode (users.test_mode). reports.py : geofence bypassée +
  is_test si mode test ON (création, confirmation terre, PATCH souple sur
  SES signalements TEST). dev_switch : _switch_scope (admin=tous,
  testeur=liste bêta, autres=403 — remplace « ouvert à tous », TODO
  pré-publication soldé).
- Frontend : Profil → switch « Mode test bêta » + tuile bascule (testeurs),
  tuile « Bêta-testeurs — gestion (admin) » → /profile/beta-testers
  (ajout/suppression, window.confirm sur web) ; settings.tsx gated ;
  badge .sm-test-badge (MarineMap) + chip report-test-badge (fiche).
- QA : comptes BetaTest1 0688776655 / BetaTest2 0688776656 (OTP 123456),
  fixture TEST f313c81ea94b4338aca0da4b50e71389 (~47.658,-2.760).
  SMS toujours MOCKÉ (code 123456) — choix armateur pour la bêta fermée.
- Pytest testeur : /app/backend/tests/test_iter90_beta_mode.py (19 tests).

## 🚀 V2 « MODE NAVIGATION COMPLET » (19/07/2026, directive armateur)
- V1 = correctifs uniquement. Groupes (4.3/4.4) et évolutions liées : EN ATTENTE
  jusqu'à nouvel ordre. Nouvelle cible : routage marin type Navionics (routes
  sûres A→B selon tirant d'eau + marge ≥50 m, édition waypoints tap/drag,
  override danger consenti, signalements dans le corridor, offline 100×100 km
  avec détection MAJ SHOM).
- **Analyse complète + stratégie N0→N4 : voir `/app/memory/V2_NAVIGATION_ANALYSE.md`**
  (verrous : MNT bruts via diffusion.shom.fr/prépaquets ; moteur A* custom ;
  offline = tuiles OSM interdites en masse + décision WebView vs MapLibre natif ;
  risques : juridique, marée ZH conservatrice, pas d'ENC officielles ; préalable
  N0 : refactor map.tsx 2794 l. / MarineMap 1966 l. — régression interdite).
- ⏳ EN ATTENTE réponses armateur : zone pilote Morbihan ? V2.0 sans marée OK ?
  décision offline différée ? GO N0 (curseur opacité temps réel + refactor +
  réglages bateau tirant d'eau/marge) ?
- Demande UX actée (non codée, dans N0) : remplacer les chips d'opacité bathy
  par un CURSEUR avec aperçu temps réel.

## PROTOTYPE bathymétrie SHOM (19/07/2026, GO armateur, self-testé ✅)
- MAJ 19/07 soir (retours device armateur, iter89 ✅) :
  1. **Bouton trop haut en PORTRAIT (device)** : fabStack bottom passé de
     `insets.bottom + 44` à `44` FIXE — la barre d'échelle est relative au
     bas du CONTENEUR carte (la tab bar absorbe la safe area), ajouter
     insets.bottom double-comptait ~50 px sur Android (web insets=0 →
     invisible en preview). Gap 5,00 px validé sur 6 configs.
  2. **Réglage d'opacité** : APPUI LONG sur la goutte d'eau → popup
     « Bathymétrie SHOM — opacité » chips 30/50/70/100 % (testID
     bathy-opacity-*), persisté `sm.map.bathy_opacity` (défaut 0.7),
     `window.__setBathyOpacity` (seules les 4 couches bathy changent,
     OSM/OpenSeaMap intactes), ré-émis sur 'ready'. Toast d'activation
     mentionne l'appui long.
- Surcouche WMS SHOM open data (services.data.shom.fr/INSPIRE/wms/r —
  Licence Ouverte, attribution « Bathymétrie © SHOM », PAS pour la
  navigation officielle). Le service REFUSE les requêtes multi-couches →
  4 overlays Leaflet séparés : MNT_ATL100m + MED100m_GDL_CA + MED100m_CORSE
  (façades HOMONIM 100 m) + MNT_COTIER_MORBIHAN_TANDEM_20m (détail 20 m,
  zone de l'armateur). Opacité 0.7, seamarks OpenSeaMap maintenus AU-DESSUS
  (bringToFront).
- Toggle : bouton goutte d'eau `map-bathy-toggle` dans la colonne FABs
  (entre refresh et recentrage), OFF par défaut, persisté `sm.map.bathy`,
  toast d'info. MarineMap : prop `bathymetry` + `window.__setBathy(on)`
  (aucune requête WMS tant que OFF — « ne casse rien »), ré-émis sur 'ready'.
- Validé e2e web : OFF = 0 requête SHOM ; ON = 100 GetMap + rendu relief ;
  zoom 13 Golfe du Morbihan = chenaux visibles (MNT 20 m) avec bouées
  au-dessus ; re-OFF + pan = 0 requête ; boot avec flag = overlay restauré.
- ⚠️ Leçon dev : 3 search_replace PARALLÈLES sur map.tsx se sont écrasés
  silencieusement (édits « réussis » absents du fichier) → toujours
  séquencer les édits d'un MÊME fichier.

## Échelles carte v3 — TEST armateur (18/07/2026, self-testé ✅, RÉVERSIBLE)
- FIX chevauchement (18/07, bug armateur avec capture, iter88 ✅) : la barre
  Navionics (WebView, bottom 10 px, ~28 px de haut) passait SOUS le bouton
  Signaler centré (portrait ET paysage, récidive au 2e cycle de rotation).
  Fix map.tsx : fabStack remonté à `insets.bottom + 24 + 40` (dégagement
  déterministe, indépendant des fluctuations d'insets entre bascules).
  Validé iter88 : 7/7 orientations (390×800, 800×390, 360×740, 3 cycles)
  overlap = 0 px, gap 25 px, centrage ±0,01 px, zoom-out ×6 → « 500 km »
  toujours 0 chevauchement, flux Signaler OK. Note P3 : +40 = magic number
  (constante partagée possible si le CSS de #sm-ruler-nav évolue).
- MAJ 18/07 (2e demande) : barre Navionics ÉLARGIE à ~80 % de largeur —
  candidats densifiés (pas ~1,25×, m/km/NM), plus grande valeur ronde ≤ dH
  → barre 60-80 % du viewport ; libellé aligné à GAUCHE (padding 6 px) pour
  rester lisible sous le bouton Signaler centré qui peut recouvrir le milieu.
  Vérifié e2e : « 30 km » 75 %, zoom-out → « 60 km » 75 %, « 100 km » 62 %.
- MAJ 18/07 (3e demande) : barre CENTRÉE horizontalement (left:50% +
  translateX(-50%)) quelle que soit l'orientation. Vérifié e2e : centre
  exact 195/390 portrait et 400/800 paysage, aucun chevauchement (fab +40).
- MAJ 19/07 (verdict armateur : « échelle ok, bouton trop haut ») :
  séparation FIXE 5 px bouton↔barre (fabStack bottom = insets.bottom + 44 ;
  barre = 39 px depuis le bas de la WebView). Vérifié e2e : gap 5,0 px en
  portrait, paysage et re-portrait.
- MAJ 18/07 (4e demande) : libellé (« 30 km ») CENTRÉ dans la barre
  (text-align:center, padding-left retiré). Vérifié e2e : texte centré 195/390.
- Demande user : « supprime "notre échelle" en bas, ne mets que l'échelle type
  Navionics en bas ; à gauche tu laisses tel quel ; centre le bouton Signaler.
  C'est un test, je te dirai si on conserve ou si on revient en arrière. »
- Fait (MarineMap.tsx) : règle HORIZONTALE du bas (#sm-ruler-h) SUPPRIMÉE
  (création, CSS, setRuler simplifié vertical-only) ; règle VERTICALE gauche
  inchangée ; barre Navionics descendue à bottom:10px et rendue COMPACTE
  (plus grande valeur ronde ≤ 25 % du couloir de référence → ≤ 20 % du
  viewport, ne passe jamais sous le bouton Signaler centré). La métrique dH
  (segment 10→90 % du viewport) est conservée comme référence.
- Fait (map.tsx) : bouton « Signaler » CENTRÉ horizontalement (fabStack
  left:0/right:0, fabRow justifyContent:center) ; colonne d'icônes en
  ABSOLU bas-droite (fabCol position:absolute right:spacing.md bottom:0).
- Vérifié e2e web : sm-ruler-h absent, verticale OK, barre Navionics
  « 5 km » 52 px à gauche (fin x=91 < bouton x=126), Signaler centré 195/390.
- ⚠️ ROLLBACK possible si l'armateur n'aime pas : restaurer mkRuler h + CSS
  #sm-ruler-h + setRuler h + bottom:34px + cap ≤ dH + anciens styles fabStack/
  fabRow/fabCol (voir git).

## Compteur vitesse — troncature > 100 km/h corrigée (15/07/2026, iter80 ✅)
- Au-delà de 100 km/h (« 102.4 » = 5 caractères), les chiffres du popup
  compteur (SpeedometerOverlay) étaient tronqués. Fix : fontSize déterministe
  selon la longueur (≤4 chars → 52, 5 → 42, ≥6 → 34) + minimumFontScale 0.55.
- Validé iter80 (geolocation monkey-patchée à 30 m/s = 108 km/h) : « 108.0 »
  complet, cap 90° E, régression basse vitesse OK, fermetures OK.

## Confirmation « à la Waze » par passage à proximité (15/07/2026, iter79 ✅)
- GO armateur après analyse (6 garde-fous validés) : quand le bateau EN ROUTE
  (≥0,8 m/s, vitesse dérivée des positions si GPS speed absent) passe à
  ≤ 500 m d'un signalement actif PUIS le DÉPASSE (min distance + ré-éloignement
  ≥100 m), popup « {Type} — toujours là ? » : « Oui, vu ! » / « Non, pas vu. »,
  barre de progression + fermeture auto 7 s (aucune réponse = neutre),
  vibration courte à l'affichage (native).
- Garde-fous : jamais pendant une alerte (question mise en attente, posée
  quand l'écran se libère), jamais ses propres signalements ni déjà confirmés
  par soi, 1 question/signalement/session, espacement ≥60 s, 1 popup à la fois.
- Backend : « Oui » → POST /confirm {source:'proximity'} = +1 pt (au lieu de
  +2, anti-farming) + TTL glissant + RESET des denials. « Non » → NOUVEAU
  POST /api/reports/{id}/deny : effet seulement si info fraîche (créé <30 min
  OU confirmé <30 min) sinon none ; retrait (expires_at=now, non destructif,
  marqueur denied_by_community) si <30 min jamais confirmé OU ≥2 Non ; sinon
  TTL ramené à ≤15 min ; 422 sur son propre signalement ; 1 Non/user.
- Fichiers : routers/reports.py (deny_report), src/lib/proximity-confirm.ts
  (machine à états inZone/minD/asked + pendingRef), ProximityConfirmCard.tsx,
  map.tsx (answerProximityYes/No, rendu !activeAlert), client.ts.
- Validé iter79 (pytest backend 4/5 + revue, e2e web garde-fou alerte) +
  self-test visuel complet : popup → Oui → toast « +1 pt de grade », popup
  jamais superposée à l'alerte. Seuil 500 m unique (à ajuster après données).

## Micro-ajustements alerte (15/07/2026 soir, self-testés ✅)
- Pastille « Alerte stoppée / Réactiver » : fermeture AUTO 5 s après l'appui
  sur « Stopper l'alerte » (timer stopPillTimerRef, annulé si réactivation /
  nouvelle alerte / fermeture). Vérifié web : visible t+1 s, disparue t+6 s.
- Réglages : libellé « Alertes activées » → « Alertes sonores activées ».

## 4 points armateur du 15/07 après-midi (iter78 ✅)
1. **Crash au partage de capture d'écran depuis la carte** : logs analysés —
   aucune erreur JS, redémarrage propre = Android TUE Expo Go en arrière-plan
   (pression mémoire pendant que Gmail est au premier plan ; l'écran carte
   porte un gros WebView, la page Réglages non → cohérent). PAS de fix code
   possible (LMK système) ; s'améliorera nettement en build de production.
   Session/mode nav/réglages persistés → l'app se relance dans le bon état.
2. **Ligne de cap non centrée dans le cône à certains caps (capture user)** :
   la ligne rouge était UNE corde droite de 500 km (une géodésique courbe en
   Mercator) et les bords longs du couloir de simples cordes. Fix MarineMap :
   ligne échantillonnée tous les 25 km (21 pts) + bords longs du couloir
   échantillonnés (~24 segments, step ≥2 km). Validé iter78 (21 pts trail).
3. **Répétitions dans le bandeau d'alerte** : chips 0/1/2 ajoutées à la
   variante « alert » d'AlertSettingsPanel (Vigie ET Nav), testID
   `alert-banner-reps-*`, hint dynamique, persistance commune (repetitions).
4. **Stop = silence définitif** : verrou `alertStoppedRef` (map.tsx) — après
   « Stopper l'alerte », plus AUCUNE répétition ne peut sonner (garde dans le
   tick du timer en plus du clearAlertTimer) ; la réactivation via la
   pastille rejoue le son et relance les répétitions. Une alerte d'un AUTRE
   signalement garde le droit de sonner (sécurité). Validé iter78 (0 play
   sur 40 s après stop ; réactivation → play + répétition 15 s).

## Cooldown strict des alertes — 5 min (15/07/2026, iter77 ✅)
- Bug terrain : re-déclenchement d'une alerte < 1 min après la 1re (mode Nav).
  Cause : la condition de ré-armement Nav « hors du cône ET > 1,2× zone
  Vigie » pouvait être satisfaite par une simple embardée de cap pendant
  10 s en pleine approche → ré-armement → re-entrée cône (3 s) → re-alerte.
- Fix `sound-alert.ts` : `lastAlertAtRef` (jamais effacée par le ré-armement,
  purgée seulement à la clôture) + `REALERT_COOLDOWN_MS = 5 min` — un même
  signalement ne re-déclenche JAMAIS avant 5 min, même ré-armé. Verrou de
  présence + ré-armement inchangés.
- RÈGLE COMPLÈTE actuelle : 1 alerte par présence → ré-armement si sortie
  franche (>1,2× zone, ≥10 s) ou clôture → ET cooldown strict 5 min.
- Validé iter77 e2e (géoloc CDP : entrée → alerte, sortie franche, re-entrée
  <5 min → ZÉRO re-alerte ; déclenchement initial + corne intacts).

## Distance du cône dans le popup carte (15/07/2026, demande user) ✅
- Le popup « Cône Navigation » (bouton `map-cone-config`, visible en mode Nav)
  contient désormais, sous le slider d'angle, le réglage « Distance du cône »
  (= `zoneNavM`, MÊME réglage que « Zone de veille — Navigation » de la page
  Réglages, synchro bidirectionnelle automatique). Composant `ZoneField`
  exporté d'AlertSettingsPanel + bornes NAV_SLIDER_MAX_KM/NAV_INPUT_MAX_KM,
  testID `map-cone-distance-*`. Texte d'info obsolète corrigé (évasement
  1 km — plus de « distance dynamique vitesse × 10 min »).
- Self-testé e2e web : popup OK, défaut 9,3 km = 5 NM, saisie 12 → 12 km ·
  6.5 NM appliqué.

## Mécanisme de version / détection de MAJ (15/07/2026, GO armateur) ✅
- Backend `routers/app_version.py` : GET /api/app/version (public) →
  {latest, minimum, android_url, ios_url, message} depuis Mongo
  `app_config/_id="version"` (défauts : latest 1.5.0 = expo.version,
  minimum 1.0.0). POST /api/app/version (admin whitelist
  antoninlepinay@gmail.com) pour mettre à jour SANS redéploiement —
  c'est l'appel à faire à chaque publication store (semver validé, 422).
- Frontend `src/components/UpdateGate.tsx` (monté dans _layout) : au boot,
  fetch fail-silent (timeout 6 s) + comparaison semver avec
  Constants.expoConfig.version → locale < minimum = écran « Mise à jour
  requise » (bouton store + « Plus tard » discret, blocage DOUX — app de
  sécurité en mer) ; locale < latest = bannière haute rejetable, mémorisée
  PAR VERSION (storage signmar.update.dismissed). URLs store par plateforme
  (à renseigner via POST après publication).
- Testé e2e web (self-test) : bannière 9.9.9 + fermeture persistante après
  reload ✅, overlay requis + Plus tard ✅, POST sans auth 401 ✅, semver
  invalide 422 ✅. Config REMISE à latest=1.5.0/minimum=1.0.0 (aucune
  bannière en prod tant qu'on ne publie pas plus haut).

## Bandeau « nouveaux signalements » auto-masqué (15/07/2026) ✅
- Le bandeau `map-new-reports-banner` (« N nouveaux signalements près de
  vous ») disparaît AUTOMATIQUEMENT après 4 s (useEffect sur pollNewCount →
  pollDismiss). L'info RESTE dans la cloche : chaque signalement proche crée
  une notification persistée (server.py::send_push → NOTIF.create), vérifié.
- Q1 armateur (détection MAJ store au lancement) : RIEN d'automatique
  aujourd'hui — pas d'OTA expo-updates documenté chez Emergent (MAJ = redéploi
  + nouveau build + soumission stores). À IMPLÉMENTER nous-mêmes avant
  publication (backlog validé à confirmer) : endpoint GET /api/app/version
  {latest, minimum} + comparaison au boot (Constants.expoConfig.version) →
  bannière « Mise à jour disponible » (+ blocage si < minimum) avec lien store.
- Q2 armateur : modération Claude Haiku 4.5 via clé Emergent = payant à
  l'utilisation (tokens débités du solde de la clé universelle, ~fraction de
  centime par texte court ; photos/vision plus cher par image).

## Son d'alerte configurable + fix clignotement hors-cône (14/07/2026 soir, iter76 ✅)
- **Son d'alerte au choix** (Réglages → « Zone de veille & alertes » → « Son
  d'alerte ») : chips `alert-sound-horn` (Corne de brume, défaut) /
  `alert-sound-sonar` (Ping sonar, fichier fourni par l'armateur
  sonar-ping_loud.mp3) + bouton « Écouter » (`alert-sound-test`). Sélection =
  pré-écoute. Persisté `voiceSettings.alertSound`. ⚠️ CODE DE DÉCLENCHEMENT
  FIGÉ (exigence armateur) : playAlertHorn/stopAlertHorn/isHornPlaying gardent
  signatures et règles (non-interruption, file par distance) — seul le fichier
  joué change (alert-sound.ts : 2 players, isHornPlaying vérifie les 2,
  previewAlertSound réservé aux réglages peut couper une lecture).
- **Fix clignotement marqueurs hors-cône en Navigation** (retour terrain) :
  jitter GPS cap/position 1 Hz balayait la frontière du couloir → bascule
  gris↔couleur en boucle. Fix MarineMap.tsx updateReportsOpacity :
  hystérésis (grisage seulement si hors couloir ÉLARGI +5°/+12 % ; rallumage
  dès le couloir EXACT, IMMÉDIAT), anti-rebond 1,5 s sur le GRISAGE seul,
  premier passage immédiat, reset dimState à la sortie du mode Nav +
  nettoyage à la suppression des marqueurs ; setIcon seulement si le HTML du
  pin change (_smPinHtml — plus de recréation DOM à chaque poll).
- Le testing agent a corrigé un bug d'init (dimState/dimPending/DIM_DEBOUNCE_MS
  manquants dans l'objet SM — l'édit initial avait été perdu lors du nettoyage
  d'un fragment dupliqué en fin de fichier). Validé iter76 : chips + persistance
  + pré-écoute sonar OK, démo autopilote 1 seule transition de grisage en 15 s,
  0 pageerror. ⚠️ Stabilité du grisage à confirmer en mer par l'armateur
  (vidéos éventuelles à venir).
- **Crash photo (iter75)** : non reproduit par l'armateur après le fix OOM
  (« plusieurs tests, dans l'ensemble c'est correct ») — logs instrumentés
  photo_step en place si récidive.

## Crash photo signalement — OOM 64 Mpx corrigé (14/07/2026 soir, iter75 ✅)
- Bug terrain (Samsung A52s, Expo Go) : créer un signalement AVEC photo →
  crash natif à chaque fois (app tuée, aucun log JS, signalement perdu) ;
  sans photo OK. Logs device : 3 `logger_started` (redémarrages) sans erreur.
- CAUSE : `manipulateAsync` décodait le bitmap PLEINE RÉSOLUTION en RAM
  (Glide sans limite, issue expo #36861) — 64 Mpx ≈ 256 Mo → OOM natif
  non catchable dans Expo Go (pas de largeHeap). Le fix du 11/07 (iter57,
  « ne pas demander base64 au picker ») était nécessaire mais INSUFFISANT.
- FIX (`src/lib/image-utils.ts::toDataUri`) : natif = décodage BORNÉ via
  expo-image `Image.loadAsync({uri},{maxWidth,maxHeight})` (downsampling
  PENDANT le décodage, la pleine résolution n'entre jamais en mémoire) puis
  `ImageManipulator.manipulate(imageRef).renderAsync()` + `saveAsync`
  (nouvelle API objet, interop SharedRef) + `release()` des refs en finally.
  Web = ancien chemin canvas conservé. Appelants inchangés (new.tsx 1280,
  avatar.ts 512).
- Validé iter75 : e2e web photo (JPEG 2400×1800 → 147 Ko stockés, 0 erreur),
  sans photo OK, revue .d.ts SDK 54 complète. ⚠️ Preuve finale du fix OOM =
  sur le téléphone de l'armateur (non reproductible en web).

## 🔊 SON D'ALERTE « CORNE DE BRUME » (14/07/2026, fichier fourni par l'armateur) ✅
L'armateur a fourni `boat_horn_1_time.mp3` (un seul coup de corne, remplace le
1er fichier boat_horn.wav du même jour) : au déclenchement d'une alerte,
on JOUE CE SON TEL QUEL, UNE SEULE FOIS — aucun calcul, aucune anticipation,
aucun préchauffage. Rejoué uniquement si des répétitions sont configurées.
- Asset embarqué : `/app/frontend/assets/sounds/boat_horn_1_time.mp3` (150 Ko).
- Nouveau module : `src/lib/alert-sound.ts` (`playAlertHorn`/`stopAlertHorn`,
  expo-audio createAudioPlayer, playsInSilentMode iOS, volume max, singleton).
- Câblage : sound-alert.ts (déclenchement initial, gate `enabled !== false`),
  map.tsx (répétitions 0-2 = son + vibration, réactivation, stop/close/unmount
  coupent le son), demo-autopilot.tsx (fireAlert/réactiver + tous les stops +
  bouton mute coupe le son en cours).
- Textes AlertSettingsPanel : « rappel par vibration » → « (son + vibration) ».
- L'alerte complète = popup/bannière + CORNE DE BRUME + vibration.
- **Bug terrain corrigé (14/07 soir, iter74 ✅)** : avec PLUSIEURS signalements
  en file, processQueue enchaînait toutes les 4,3 s et chaque alerte faisait
  seekTo(0)+play → corne (~6 s) COUPÉE puis redémarrée avant la fin (confirmé
  vidéo user + logs device : 2 « sound-alert jouée » à 4,3 s d'intervalle).
  Fix : (1) playAlertHorn() IGNORE toute demande si `player.playing` (JAMAIS
  d'interruption ni de restart — règle absolue armateur), setAudioModeAsync
  via promesse lazy attendue AVANT lecture (jamais pendant) ; (2) processQueue
  attend la FIN réelle de la corne (poll isHornPlaying() 250 ms, borne 12 s)
  avant l'alerte suivante. Validé iter74 : 0 restart/0 pause intempestive sur
  40 s de file, espacement bannières 11-16,5 s, stop/réactiver OK, revue de
  code complète. Espacement réel attendu sur device ≈ 10 s entre 2 cornes.
- Validé (smoke web 14/07) : alerte → bannière → Stop → pastille Réactiver,
  0 erreur console, wav servi par Metro (200). Son audible à valider sur device.

## 🔴 AUDIO TTS/VOCAL SUPPRIMÉ (14/07/2026, iter73 — décision armateur) ✅
Le système vocal (jugé instable sur son device malgré iter68→72) a été
ENTIÈREMENT RETIRÉ. L'alerte = **popup/bannière visuelle + VIBRATION** :
- Supprimé : `src/lib/voice-player.ts` (fichier effacé), préchauffage TTS,
  choix de voix Femme/Homme, bouton « Écouter », slider « Volume des
  alertes », lecture vocale des répétitions et de la démo autopilote.
- Créé : `src/lib/alert-vibration.ts` (`vibrateAlert` / `stopAlertFeedback`).
- Conservé : bannière avec le TEXTE d'alerte (`buildAlertText`, qui définit
  aussi QUELS types alertent), répétitions 0/1/2 (= rappels par VIBRATION,
  toast « présentée N+1 fois au total »), interrupteurs « Alertes activées »
  + « Vibration », zones Vigie/Nav, garde une-alerte-par-présence + ré-armement.
- Backend : tâche de pré-génération TTS désactivée (server.py) ; routers/tts.py
  + collection tts_cache (108 MP3) laissés EN PLACE, inactifs — réactivables
  sans refaire le travail si l'armateur change d'avis.
- packages expo-audio / expo-speech toujours déclarés (non importés) — escape
  hatch volontaire, NE PAS purger sans demande.
- Validé iter73 : 0 appel /api/tts/*, 0 erreur console, réglages épurés
  conformes, démo OK, revue de code sans référence résiduelle.


## ⚠️ GEL V1.0 (13/07/2026 — directive user, PRIORITÉ ABSOLUE)
L'app est FIGÉE en V1.0 : **AUCUNE évolution / nouvelle fonctionnalité**.
Autorisés UNIQUEMENT : fiabilisation, ergonomie, ajouts de TYPES de
signalements (avec leurs conditions), correctifs — dont les signalements
audio SANS fichier son (alertes vocales muettes). Cette version part en
ligne quand elle sera 100 % fonctionnelle. Les phases 4.3 (chat de groupe)
et 4.4 (tracking live) sont SUSPENDUES jusqu'à nouvel ordre.

## Coupure du MP3 + voix robot tardive (14/07/2026, iter72) ✅
- Vidéo user #4 (analyse seconde/seconde) : MP3 naturel démarre AVEC la popup
  (fix 350 ms OK), COUPÉ à ~0,9 s de voix, puis voix ROBOT (fallback
  expo-speech) 17 s plus tard (init à froid du synthétiseur Android).
- Cause de la coupure non certaine (perte d'audio-focus transitoire ou fichier
  cache tronqué) → solution RÉSILIENTE :
  1. WATCHDOG de lecture (voice-player.ts) remplace la garde 2,5 s : poll
     400 ms ; jamais démarré ~2,8 s OU arrêt prématuré (avant durée-0,4 s,
     hors stop user/remplacement) → RELANCE le MÊME MP3 une fois (même voix) ;
     2e échec → purge du fichier suspect (mémoire+disque) + repli embarqué
     immédiat. Interval nettoyé sur tous les chemins + garde 30 s.
  2. `warmAudioPipeline` prononce « \u00A0 » à volume 0 → init RÉELLE du
     synthétiseur Android au montage de la carte (getAvailableVoicesAsync ne
     suffisait pas).
- Validé iter72 (revue de code complète, pas de fuite d'interval, bouton
  Écouter sans watchdog, smoke web 0 erreur). Événements `audio_cut_detected`
  / `tts_speech_fallback_used` loggés pour diagnostiquer sur device.

## Latence résiduelle 2 s ÉLIMINÉE (14/07/2026, iter71) ✅
- Vidéo user #3 : toujours 1,2-1,9 s entre popup et voix MALGRÉ le cache.
- **Vrai coupable** : le préfixe de 2 000 ms de SILENCE encodé ajouté à chaque
  MP3 servi par /api/tts/alert (phase K.15, anti-troncature Bluetooth). Même
  en lecture instantanée, la voix partait 2 s après la bannière. Le format
  MP3 n'était pas en cause.
- Fix : `silence_350ms.mp3` (15 trames découpées du fichier 2 s, même codec
  24 kHz mono 32 kbps) remplace le préfixe 2 s ; cache local versionné
  (`signalmar-voice2-…`) pour forcer le re-téléchargement des MP3 courts.
- Attendu sur device : voix ~0,5-0,7 s après la popup (démarrage player
  ~150-300 ms + 350 ms de wake Bluetooth). Validé iter71 : 25/25 backend
  (préfixe exact, trames alignées, <1,5 s), revue de code, smoke UI.
- ⚠️ Si un jour retour de troncature sur enceinte BT lente : envisager un
  keep-alive silencieux joué au préchauffage (approche zone) plutôt que de
  rallonger le préfixe.

## Latence audio des alertes corrigée (13/07/2026 soir, iter69) ✅
- Vidéo user : 18 s entre bannière et son (1re alerte), puis 3/3/1/1 s.
- Causes : pas de préchauffage TTS pour les signalements DÉJÀ dans la zone
  (`!inside`), fetch TTS à froid (génération OpenAI ~5 s) + timeout 5 s +
  init à froid du moteur TTS Android (~10 s) au repli.
- Fixes (voice-player.ts / sound-alert.ts / map.tsx) :
  1. `warmAudioPipeline()` au montage de la carte (session expo-audio +
     `Speech.getAvailableVoicesAsync()` réveille le moteur TTS système) ;
  2. préchauffage TTS aussi pour les signalements DANS la zone ;
  3. préchargement PARALLÈLE des MP3 de toute la file à l'enqueue ;
  4. fetch TTS DÉDUPLIQUÉ (`inflightFetch`) — play() rejoint le prefetch ;
  5. borne stricte 3,5 s au play (Promise.race) → repli immédiat sur TTS
     embarqué (déjà chaud), téléchargement poursuivi en fond (répétitions
     instantanées).
- Pire cas théorique désormais ≈ 3,5-4 s (1re alerte, texte jamais généré) ;
  ~0 s ensuite. Validé iter69 (revue de code complète + backend cache 178 ms
  + E2E web sans erreur). Confirmation à l'oreille sur device par l'user.
- **Suite 14/07 (iter70, demande user « stockés une bonne fois pour toutes »)** :
  1. Catalogue COMPLET pré-généré au démarrage backend (`_catalog_texts()` +
     `pregenerate_alert_catalog()` dans tts.py : 50 phrases × 2 voix, tâche
     de fond, uniquement les manquants, idempotent — « catalogue complet déjà
     en cache » au restart). ⚠️ SYNC obligatoire avec buildAlertText
     (voice-alerts.ts) si nouvelles phrases. tts_cache = 108 docs.
  2. `getCachedVoiceUri()` (voice-player.ts) : réhydratation du cache mémoire
     depuis le DISQUE après redémarrage app (fichiers hash déterministes) →
     lecture instantanée hors réseau. Validé iter70 : 62/62 backend (<1,5 s
     partout, ~50 ms), textes identiques au frontend caractère par caractère.

## Bug boucle d'alerte corrigé (13/07/2026, iter68) ✅
- Cause : l'ancien « cooldown 5 min » RE-DÉCLENCHAIT l'alerte complète tant
  qu'on RESTAIT dans le périmètre → boucle infinie en stationnaire (user :
  gendarmerie répétée ≥5×).
- Fix : UNE alerte par présence (`alertedAtRef.has(id)` — COOLDOWN_MS
  supprimé). Total entendu = 1 annonce + N relances bannière (réglage 0-3),
  puis SILENCE tant qu'on reste dans la zone. Ré-armement uniquement après
  sortie franche ≥10 s (hystérésis ×1,2) ou clôture du signalement.
- Défaut répétitions 1 → 3 (demande user) + migration AsyncStorage
  (`repCapMigrated` : valeur 1/absente → 3 ; choix délibéré 0/2/3 conservé).
- **RÉVISION 13/07 soir** : plafond abaissé à **0-2 répétitions** (défaut 2,
  chips 0/1/2). Clamp au chargement : toute valeur >2 → 2. À la sélection,
  toast de confirmation explicitant le TOTAL diffusé (« diffusée N+1 fois au
  total : 1 annonce + N répétitions ») — cas user « 1 → diffusée 2 fois »
  vérifié par capture.
- Validé iter68 (revue de code 4/4 + observation UI : bannière s'éteint,
  aucun re-déclenchement). À confirmer à l'oreille sur device.

## Alertes pollution + lot de test d'alarme (13/07/2026, iter67) ✅
- **Alertes vocales pollution** : `pollution_locale` + `pollution_importante`
  déclenchent maintenant l'alerte (message modulé par la vitesse, comme les
  obstacles). `pollution_cote` reste volontairement silencieuse
  (voice-alerts.ts, POLLUTION_SUBJECTS).
- **Lot de test d'alarme** : Profil → « Test d'alarme — créer 5 signalements »
  (whitelist uniquement, testID profile-alert-test-batch) → POST
  /api/dev/alert-test-batch {lat,lng} : crée 5 signalements DÉCLENCHEURS
  autour de la position (600 m OFNI [200 m → 600 m le 13/07 soir] / 1 km
  mammifère blessé / 3 km gendarmerie / 10 km pollution locale / 20 km
  pollution importante, caps espacés 72°), flag `is_alert_test`, chaque
  nouveau lot EFFACE le précédent
  (author_id). 403 non-whitelist. Navigation auto vers la carte + toast.
- Validé iter67 : backend 5/5 pytest (distances <50 m, remplacement,
  403), UI 6/6 (row, toast, 5 marqueurs, alerte du 200 m déclenchée à
  l'écran, row masquée pour compte lambda).
- **À VENIR (demande user)** : même mécanique avec 10 signalements dont
  certains NON déclencheurs (pour tester les faux positifs).

## Régression carte corrigée (13/07/2026 soir, iter66) ✅
- Régression MAJEURE introduite avec DraggableZoomButtons (iter65) : wrapper
  `GestureHandlerRootView` PLEIN ÉCRAN → sur Android natif, la vue RNGH
  n'honore pas `pointerEvents="box-none"` et AVALAIT tous les touchers
  (carte morte : ni pan, ni taps, ni zoom). Diagnostiqué via vidéo user.
- Fix : UN SEUL GestureHandlerRootView global (app/_layout.tsx) ;
  DraggableZoomButtons + SpeedometerOverlay → simples View absoluteFill
  box-none (PhotoViewer garde le sien : hiérarchie séparée dans un Modal
  natif, légitime). RÈGLE : ne JAMAIS re-nester de GestureHandlerRootView.
- iter66 : pan + taps marqueurs + zoom + speedo + FABs tous validés sur web,
  revue de code native OK.


## Vision
Application mobile (iOS + Android, Expo) — "Waze pour la mer". Sécurité,
urgence, simplicité (signalement en <3 taps), dark mode. Cible : 500k utilisateurs.

## État actuel (juillet 2026)
Application complète et fonctionnelle :
- Carte Leaflet (WebView) avec marqueurs, filtres, rayon, mode démo anonyme (30 signalements seedés `is_demo`).
- Signalements v2 (cahier des charges 27/06) : types `autorites, secours, obstacle_nav, animal_marin, pollution, autre` + sous-types libres + extras. TTL glissant par type. Géofencing "en mer" (Open-Meteo Marine, fail-open).
- Modes Vigie vs Navigation, alertes vocales TTS de proximité, ping radar.
- Cône de dérive (vent Météo-France AROME/ARPEGE + courant Open-Meteo, leeway par sous-type, cap éditable par utilisateurs fiables ≥60%).
- Gamification : points, grades Marine Nationale (21 échelons), fiabilité (`reliability_pct` = source de vérité, défaut 50%), streaks, quotas anti-abus.
- Groupes privés + invitations ciblées + sync contacts (SHA-256 E.164).
- Parrainage viral : code unique, landing `/join?ref=`, bonus grade + mois Premium.
- Notifications in-app (cloche) + relais push Emergent (clé placeholder → injectée à la publication).
- Comptes de test switcher (Phase T) : 5 comptes whitelistés, mdp partagé `123454321`.

## Architecture P0 (scaling 500k) — VALIDÉE ✅ (09/07/2026)
1. **Rate limiting SlowAPI** : `/auth/login` + `/auth/register` 5 req/5min/IP (429 ensuite),
   `/auth/google/session` 10/5min, `/auth/logout` 30/min. Clé = 1er X-Forwarded-For.
   Bypass QA : header `X-RateLimit-Bypass` == `RATE_LIMIT_BYPASS_TOKEN` (backend/.env).
2. **Notifications géo-indexées** : index `2dsphere` sur `users.last_loc` (GeoJSON Point,
   backfill auto au boot), fan-out `$geoWithin/$centerSphere` + filtre rayon/muted par user,
   dispatch via FastAPI `BackgroundTasks`, chunks de 100 destinataires.
3. **server.py découplé** : `core/` (db, auth, drift, points, referral, subscription,
   notifications, rate_limit, friends, meteofrance) + `routers/` (auth, reports, moderation,
   chat, profile, weather, tts, diagnostics, friends, notifications, groups, contacts, dev_switch).

## Fonctionnalités promo / conversion (09/07/2026) ✅
- **Landing /join avec carte live** : la page parrainage (`GET /join` + alias `GET /api/join`,
  seul chemin accessible via l'ingress Emergent) embarque une mini-carte Leaflet affichant
  en direct les ~30 signalements démo (`/api/reports` anonyme), marqueurs colorés par type,
  fitBounds auto. Bannière « Invité par <pseudo> » si code valide.
- **Démo autopilote 90 s** (`/demo-autopilot`, sans compte) : séquence à VITESSE RÉELLE
  (20 nds, aucun accéléré) 100 % pilotée par la PROXIMITÉ. Cône Navigation = géométrie de
  l'app réelle : évasement 30° / corridor parallèle 5 km (zoom auto 13 en nav via nouveau
  `MarineMap.setZoom` instantané, 15 en Vigie). Mammifère mort pré-existant placé à
  5,25 km : GRISÉ hors corridor, s'allume + alerte immédiate à l'entrée (t≈45). OFNI
  publié en Vigie statique t≈7 (alerte immédiate dans radar 1 km), gendarmerie publiée
  dans le corridor t≈30, pollution t≈63. TTS voix femme PRÉCHAUFFÉE au montage
  (`prefetchAlertVoice` → cache backend, corrige la voix muette du 1er lancement).
  Bouton Stop → pastille persistante « Alerte stoppée / Réactiver / ✕ ». Radar
  auto-réparé (fiable 1er lancement + replay). CTA à t=78. Entrées : onboarding
  (dernier slide) + haut de l'écran Profil.

## Système d'alertes configurable + interruption (09/07/2026) ✅
- **Panneau `AlertSettingsPanel`** (réutilisé à 3 endroits) : rayon d'alerte (slider log
  0,3-20 km, aimant 1 NM, saisie précise), types déclencheurs générés DYNAMIQUEMENT depuis
  `REPORT_TYPES` (liste d'exclusion `mutedTypes` → nouveaux types actifs par défaut),
  répétitions 0-3 (défaut 1, toutes les 15 s). Stockage local `voiceSettings` (AsyncStorage).
- **Carte** : FAB cloche+engrenage (`map-alert-settings`) → bottom sheet « Réglage des
  alertes ». Le radar Vigie visualise désormais exactement le rayon d'alerte sonore
  (plus de max() avec notify_radius_km).
- **Alerte active** : bannière `map-active-alert` avec bouton rouge « Stopper l'alerte »
  (coupe son+vibreur) + réglages rapides en dessous. Stop → PASTILLE persistante
  « Alerte stoppée / Réactiver / ✕ » (clic par mégarde récupérable). Répétée N fois/15 s
  si non stoppée, puis extinction automatique. Watcher : callback `onAlert` + filtre
  `mutedTypes`.
- **Paramètres** : section « Alertes sonores à bord » (panneau complet, incluant le bloc
  « Voix & vibration » restauré : switch activation, choix voix Femme/Homme + Écouter,
  switch vibration — perdu lors d'une ancienne restructuration ; le bouton mort
  « Réglages — alertes vocales » qui s'auto-référençait a été supprimé, 09/07).
- **Profil** : bouton « Voir la démo (90 s) » tout en haut (sobre, bordure orange).
- À FAIRE (nécessite build natif + notifications) : alerte sur écran verrouillé
  rejetable par glissement (comportement OS standard des notifications).

## 5 retours user traités (13/07/2026, iter65) ✅
1. **Précision des taps marqueurs** (bug aléatoire « éjecté ») : cause = chrono
   de recentrage expirant PENDANT le tap → la carte bougeait sous le doigt.
   Fix : listeners capture `touchstart/mousedown/wheel` sur #map → tout contact
   repousse `lastUserPan` de 5 s (MarineMap HTML).
2. **Plus de recentrage immédiat au retour d'un détail** : `SM.grantGrace()` +
   handle `grantRecenterGrace()` appelé dans le useFocusEffect de map.tsx ;
   `setNavMode(on, skipRecenter)` pour re-sync Nav sans recentrer. Recentrage
   après 5 s d'inactivité (comportement demandé). Diagnostiqué via la VIDÉO
   envoyée par l'user (upload support).
3. **Autorités/secours stationnaire ou contrôle** : carte Cap affiche l'ÉTAT
   (« Stationnaire »/« En contrôle ») au lieu de « non défini ». Modifier →
   HeadingEditModal propose « Vitesse estimée » (défaut 10 nds, steppers ±1 +
   saisie, testIDs heading-speed-*) ; PATCH /api/reports/{id} accepte
   `speed_knots` (AuthorEditIn) et bascule `activity=navigation` (+vitesse
   défaut 10 si absente) → flèche de projection sur la carte.
4. **Boutons zoom déplaçables** (`DraggableZoomButtons.tsx`, testID
   map-zoom-stack) : appui long 320 ms + glisser (comme le compteur), position
   persistée compte user (`PUT /profile/preferences {zoom_btn_pos}` →
   serialize_user) + copie AsyncStorage `sm.zoomstack.pos`.
5. **Volume des alertes** : `voiceSettings.volume` (défaut 1.0 = max), slider
   « Volume des alertes » dans AlertSettingsPanel (panneau full), appliqué au
   player MP3 + fallback expo-speech. Plafond réel = volume média du device.
- Vibration coupée sur web (bruit console navigator.vibrate).
- Tests : iteration_65 — backend 7/7 nouveaux + 19 régression, UI validée
  (recentrage vérifié par revue de code, iframe cross-origin non sondable).

## Envoi de captures vidéo au support (13/07/2026) ✅
- **Backend** (routers/diagnostics.py) : upload CHUNKÉ 512 Ko base64 —
  `POST /api/support/upload/{init,chunk,complete}` (init auth requis, 2000 chunks
  max ~1 Go, garde chunks manquants 422). Assemblage dans
  `/app/backend/uploads/support/` + méta Mongo `support_uploads`.
- **Frontend** : `src/lib/support-upload.ts` (`pickAndSendSupportRecording` —
  galerie vidéos+images, permission contextuelle avec « Ouvrir les réglages »,
  lecture mémoire-safe blob.slice+FileReader par chunk) branché dans
  `/diagnostic` : section « Capture vidéo / écran » (visible pour TOUS) avec
  bouton `diag-send-recording` + barre de progression (`diag-upload-progress`).
- Testé e2e (13/07) : login OTP → init → 3 chunks 1,3 Mo → complete (taille
  exacte), garde chunk manquant 422, init sans auth 401, doc Mongo OK, UI OK.
- **Fix natif (13/07, retour user « pas de bouton »)** : lecture des chunks sur
  iOS/Android via `expo-file-system/legacy` `readAsStringAsync` base64
  position/length (`fetch(file://).blob()` échoue en natif) ; web garde
  blob.slice+FileReader. Bouton confirmé visible (testing agent iter64 : e2e web
  complet — picker → progress → toast → fichier 1,5 Mo assemblé + doc Mongo ;
  backend 4/4). Cause probable côté user : bundle Expo Go périmé (rescanner le QR).
  LogBox `removeChild` (shim web picker, dev only) masqué.
- **Compression + rétention (13/07)** : iOS = ré-encodage vidéo à la sélection
  (VideoExportPreset + UIImagePickerControllerQualityType Medium) ; Android =
  transcodage IMPOSSIBLE en Expo Go (nécessiterait build natif +
  react-native-compressor) → plafond 100 Mo (`MAX_UPLOAD_BYTES`, alerte claire).
  Rétention 12 h backend : `purge_expired_support_uploads()` (diagnostics.py)
  appelée par `_archive_loop` (10 min) — docs Mongo + fichiers + chunks tmp
  orphelins + sessions mémoire >6 h. Testé : doc/fichier/chunk de 14 h purgés,
  récents conservés. Premier upload réel user reçu (23 Mo, 13/07 16:20).
- ⚠️ Sélection galerie réelle testable uniquement sur téléphone/web (picker natif).

## Premium offert 1 an + paliers de points + invitations parrain (10/07/2026) ✅
- **Bug fix inscription** : après le code OTP (nouveau compte), focus auto sur le
  champ pseudo + scroll au-dessus du clavier (login.tsx, scrollIntoView).
- **Premium offert 1 an** à chaque compte (dérivé de created_at, aucun champ) —
  get_subscription_state renvoie free_year_until/free_year_active, is_premium =
  max(année offerte, mois gagnés). Valable pour comptes existants (admin inclus,
  qui garde ses bypass de signalement).
- **Règle points→mois (écrase l'ancienne)** : filleul actif = +20 pts (referral.py,
  inchangé) ; try_award_bonus ne donne PLUS de mois direct (months_awarded=0) ;
  chaque palier de 100 pts GAGNÉS = +1 mois Premium auto (core/points.py
  check_point_months, champs points_premium_baseline — migré = points actuels au
  10/07, NON rétroactif — et points_months_awarded). Mois empilés après l'année
  offerte. Aucune tacite reconduction, renouvellement manuel.
- **Page Abonnement refaite** : « Premium offert » + pill 1ʳᵉ année, progression
  « Prochain mois offert X/100 pts », règles à jour, carte engagements (paiement
  crypté / pas de reconduction / seule la facture conservée).
- **Invitations parrain** (routers/referral_invites.py, collection
  referral_invitations, TTL 60 j, index uniques) : POST /api/referral/invitations
  (auth, hashes sha256 E.164 — enregistrées depuis share-invite à l'envoi des
  SMS) ; POST /api/referral/pending (public, par téléphone) ; POST
  /api/referral/resolve-sponsor (public, par hashes d'un contact) ; suppression
  auto à la création du compte (hook auth.py, 2 chemins).
- **Inscription** : carte « Un marin vous a invité » (choix du parrain →
  code pré-rempli, bandeau vert annulable) + bouton « Rechercher mon parrain
  dans mes contacts » (permission → recherche par NOM → resolve-sponsor).
- Tests : iteration_47 — backend 8/8 pytest, UI validée. Bug corrigé par le
  testing agent : double JSON.stringify dans client.ts (body doit être un objet
  brut, le helper request() sérialise lui-même) + auth:false sur endpoints publics.

## Parrainage par contacts + SMS groupé (10/07/2026) ✅
- **Nouvel écran `/share-invite`** : mécanique UNIQUE de partage — choix multi
  de contacts du téléphone (recherche par NOM, insensible accents), UN SMS
  groupé prérempli (expo-sms, l'user appuie Envoyer — envoi auto interdit par
  iOS/Android) avec l'URL d'affiliation. Contrat permissions complet (intro →
  refus retry → Ouvrir Réglages), lien « Partager autrement… » (feuille
  classique) sur chaque état, fallback web dédié. Mode signalement via params
  `type_label/coords/description`.
- **URL d'affiliation** : `signalMarInviteUrl()` pointe temporairement sur
  `EXPO_PUBLIC_BACKEND_URL/api/join?ref=CODE` (landing fonctionnelle) —
  TODO(release) : repasser sur signalmar.app/i/CODE quand le domaine sera actif.
- **Entrées branchées** : ShareAppVisual (profil + réglages, bouton → écran,
  lien classique discret dessous), page Abonnement (bouton Parrainer), page
  signalement (icône partage → écran avec infos du signalement ; l'ancien
  partage screenshot ViewShot/expo-sharing a été retiré).
- **ShareAppVisual v2** : titre « PARTAGEZ L'APP ! » agrandi avec pastille
  mégaphone, tagline sur lignes séparées, ligne « ✨ … et gagnez des points ! ».
- **Zones de veille — nouvelles bornes** : Vigie 200 m→20 km ; Nav 200 m→500 km
  au slider, saisie manuelle jusqu'à 1000 km. Le rayon de fetch/affichage carte
  s'étend automatiquement à max(200 km, zones) (cap API 1000 km).
- Rappel règles parrainage (inchangées, page Abonnement) : filleul via lien →
  compte lié → 1er signalement confirmé par un marin externe à ses groupes →
  +1 mois Premium parrain (+20 pts). Caps : 10 pending / 12 mois.
- ⚠️ Contacts + composeur SMS : testables uniquement sur téléphone (Expo Go ok).

## Refonte onglet Profil (10/07/2026, maquette user) ✅
- `(tabs)/profile.tsx` réécrit : carte profil (engrenage Réglages haut-droit,
  pills Mes amis/Groupes autour de l'avatar éditable, pseudo éditable modal,
  pill grade+pts → RanksModal, pill fiabilité → /profile/reliability, tagline
  + gros bouton « Partager SignalMar »), 2 tuiles stats, « MON HISTORIQUE »
  REPLIÉ par défaut (double flèche chevron-expand/collapse, pagination 5/p),
  Se déconnecter, rangées Abonnement & parrainage / Diagnostic / Comptes de
  test (whitelist), liens discrets côte à côte « Voir la démo » + « Revoir
  l'intro », disclaimer. Supprimés : carte abonnement premium détaillée,
  section Communauté, tuile Groupes, bouton démo en haut.
- **Barre du haut de la carte** réordonnée (demande user) : GPS · compteur de
  vitesse (pill compacte kn, remontée du bas) · Types de signalements ·
  bouton Réglages (engrenage → /profile/settings) · cloche notifications.
- NOTE : /profile/settings refait le 10/07 selon maquette user : hero
  « Réglages avancés » → section « Zone de veille & alertes » (panneau full)
  → visuel principal de partage (composant `ShareAppVisual`, réutilisé sur la
  carte profil : tagline + gros bouton + ligne « ✨ … et gagnez des points ! »)
  → rangées Abonnement & parrainage / Diagnostic / Comptes de test →
  Se déconnecter en toute fin. Historique/stats/intro/disclaimer retirés
  (vivent sur l'onglet Profil — plus de doublon).

## Fusion « Zone de veille » + recentrage 5 s (10/07/2026) ✅
- **Fusion des 2 rayons d'alerte** (notify_radius_km push + baseRadiusM sonore) → UNE
  notion « Zone de veille », réglée par mode : `zoneVigieM` (défaut 2 NM, rayon radar
  360° = zone, diamètre = 2×) et `zoneNavM` (défaut 5 NM, longueur FIXE du cône Nav —
  l'ancienne formule vitesse×10 min est supprimée). Stockage local voiceSettings +
  migration auto de l'ancien baseRadiusM. Zone Vigie synchronisée backend
  (`notify_radius_km`) ; « Types de notification » = liste UNIQUE (mute son local
  `mutedTypes` + push backend `muted_types`).
- **Bouton « 200 km » supprimé** de la carte (rayon d'affichage interne fixe 200 km,
  `DISPLAY_RADIUS_KM`). Popup engrenage (`map-alert-settings`) allégée : 2 sliders
  zones (affichage dynamique « X km · Y NM », saisie manuelle, granularité 0,1 km)
  + types + bouton « Tous les paramètres » → /profile/settings.
- **Alertes sonores** : rayon de déclenchement = zone du mode courant (Vigie 360°,
  Nav = cône) via `alertRadiusM` passé au watcher (`computeAlertRadiusM` supprimé).
- **Page /profile/settings** : bloc profil (avatar/pseudo/grade/fiabilité/partage)
  REMPLACÉ par le visuel « Réglages avancés » (`settings-hero`) ; sections
  « Notifications » + « Alertes sonores » fusionnées en « Zone de veille & alertes »
  (panneau complet : zones, types, répétitions, voix & vibration). Pseudo/avatar
  s'éditent désormais uniquement... nulle part sur cette page (l'utilisateur
  réorganise l'onglet Profil de son côté — visuels à venir).
- **Recentrage carte** : déplacement libre en Vigie ET Navigation ; recentrage auto
  5 s après la FIN du geste (dragend/zoomend, flag `userDragging`, avant : 3 s dès
  le dragstart et Nav uniquement). Jamais pendant le mode placement (crosshairOn) ;
  flyTo programmatique accorde aussi 5 s de grâce.
- Tests : iteration_46 (7 pytest backend + UI complète) — tout passe.

## Fix rotations carte/flèche + polling 1 s (09/07/2026 soir) ✅
- Polling fou (1 req/s `listReports` vu dans les logs device) : `fetchReports` dépendait
  de `userLoc` (MàJ chaque seconde) → identité changeante → useFocusEffect en boucle.
  Fix : refs miroirs `userLocRef`/`radiusRef`, deps réduites à `[selectedTypes]`.
- Flèche rouge tournant sur elle-même en Vigie : cap GPS accepté à l'arrêt (bruit
  aléatoire). Fix : cap GPS uniquement si vitesse ≥ 0,6 m/s + deadband 2° dans
  `smoothHeading` (le compas gère l'arrêt).
- Rotations anormales de la carte au lancement : pics de vitesse GPS au démarrage à
  froid déclenchaient le course-up sur un seul fix. Fix : 3 mises à jour qualifiantes
  consécutives requises (`courseUpStreakRef` dans MarineMap) ; retour nord-haut immédiat.
- « Cannot connect to Metro » : artefact websocket HMR dev via proxy — bénin,
  absent des builds production.

## Fix Expo Go « Something went wrong » (09/07/2026) ✅
- Cause : import statique de `expo-notifications` (push retiré d'Expo Go depuis SDK 53)
  dans `push.ts` + `_layout.tsx` (ERROR au boot Android Expo Go, canal créé au niveau
  module) + cache Metro vicié après redémarrages répétés.
- Fix : imports DYNAMIQUES gardés (skip si `Constants.appOwnership === "expo"` ou web),
  setup canal déplacé dans `setupNotifications()` async, cache Metro purgé.
- NOTE OPÉRATIONNELLE : chaque restart du serveur Expo casse les sessions Expo Go
  actives (rescan du QR nécessaire) — comportement normal en dev.

## Corrections session 09/07 (audit post doom-loop)
- **Bug backend** : rapports démo masqués par le filtre d'archivage 48h → exemptés (`is_demo`).
- **Bug backend** : `serialize_user` utilisait l'ancienne formule pos/neg pour la fiabilité
  alors que l'enforcement lit `reliability_pct` → unifié sur `user_reliability()`.
- Photos démo : préfixe `data:image/png` corrigé en `jpeg` + recompression ≤200KB
  (seed compresse désormais à la génération).
- Seed démo : `created_at` 12-36h dans le passé (le mode démo anonyme force min_age 12h).
- Tests modernisés : anciens types v1 → v2, mot de passe obsolète, fixtures non-idempotentes,
  bump fiabilité via DB directe. Bypass rate-limit auto-injecté par `tests/conftest.py`.

## Stack
- Expo SDK 54 + Expo Router, WebView+Leaflet, expo-location, expo-image-picker, expo-secure-store, expo-notifications.
- FastAPI + Motor + bcrypt + PyJWT + httpx + Pillow + SlowAPI + relais push Emergent.

## Endpoints clés
- Auth (Phase A) : `POST /api/auth/otp/{request,verify}` — téléphone FR (06/07) + OTP SMS
  mocké (`123456`), création de compte avec pseudo custom + code parrain, JWT identique.
  `POST /api/auth/{register,login}` conservés en legacy/QA (suite pytest, seed comptes test).
  `google/session`, `logout`, `GET|PATCH /api/auth/me` inchangés.
- Reports : `GET|POST /api/reports`, `GET|PATCH|DELETE /api/reports/{id}`, `POST /api/reports/{id}/confirm` (TTL glissant + push proximité async)
- Profil : `GET /api/profile/me`, `POST /api/profile/{avatar,location,ping-open}`, `PUT /api/profile/preferences`, referral/friends/subscription
- Groupes : `/api/groups/*`, `/api/invitations/*`, `/api/contacts/match`
- Météo : `GET /api/weather/marine`, diagnostics Météo-France
- Landing parrainage : `GET /join?ref=CODE` (hors /api)

## Env
- backend/.env : `MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `EMERGENT_PUSH_KEY=placeholder`,
  `METEOFRANCE_APPLICATION_ID`, `RATE_LIMIT_BYPASS_TOKEN` (QA uniquement).

## Tests
- Pytest backend : **256 passés, 1 skip env** (`/app/backend/tests/`), incl.
  `test_iteration_37_p0_audit.py` (12 tests P0 dédiés, testing agent 09/07).
- Credentials : voir `/app/memory/test_credentials.md`.

## ⚠️ REPRISE POST-FORK (plan confirmé par l'utilisateur, juin 2026) — NE RIEN OUBLIER
L'utilisateur va d'abord donner de NOUVELLES demandes de peaufinage/débogage juste après
le fork → les traiter en priorité, PUIS dérouler ce plan validé (4 retours en attente) :
1. **P0 Bug clavier login** : champ de recherche parrain invisible quand le clavier
   s'ouvre (`(auth)/login.tsx`) → corriger le scroll/KeyboardAvoidingView. Tester via testing_agent.
2. **P0 Recherche contacts unifiée par NOM** : ~~friends.tsx~~ FAIT (11/07, voir session fork).
   Reste : vérifier l'intégration de `ContactNameSearch` dans le parrainage (share-invite.tsx).
3. **P0 Écran Diagnostic par rôle** : ~~FAIT~~ (11/07, gating `advanced` appliqué).
4. **P0 Échelle carte** : ~~FAIT~~ déjà implémentée (MarineMap.tsx, échelle
   custom 10/07) — confirmé par l'utilisateur le 11/07, ne PAS re-planifier.
Ensuite : Phase 4.3 Chat de groupe, Phase 4.4 Tracking live.

## Prochaines étapes (priorisées) — ⚠️ cadrées par le GEL V1.0 (voir en tête)
- **P0 fiabilisation** : signalements audio sans fichier son (alertes vocales
  muettes) — à diagnostiquer et corriger.
- P0 Bug clavier login (champ recherche parrain masqué) — toujours ouvert.
- Vérif ContactNameSearch dans share-invite.tsx.
- **Attente user** : réorganisation de l'onglet Profil (visuels à venir).
- ~~Phase 4.3 chat de groupe / 4.4 tracking live~~ SUSPENDUES (gel V1.0).
- ~~P1 Phase A — Inscription OTP téléphone~~ **FAIT (10/07)** : `core/otp.py` + `core/sms.py`
  (mock `123456`), endpoints `/api/auth/otp/*` (cooldown 30 s, 5 SMS/h, 5 essais max,
  expiration 5 min, hash sha256 du code), UI unifiée login/inscription dans
  `(auth)/login.tsx` (autofill `oneTimeCode` iOS / `sms-otp` Android, pas de READ_SMS),
  `register.tsx` → redirect. France uniquement (+33, 06/07) — international plus tard.
  Google/email retirés de l'UI (backend conservé pour QA/legacy).
- **P1 Phase 4.3 — Chat de groupe** : polling 10s, 1 photo max/message, JPEG 800px compressé.
- **P1 Phase 4.4 — Tracking live** des membres du groupe sur la carte (+ mode fantôme).
- P2 : smart-links de téléchargement dans les SMS/WhatsApp d'invitation de groupe.
- P2 Phase F : modération auto (Claude Haiku 4.5 via clé Emergent) texte + photos.
- P2 : intégration marées SHOM (data.gouv.fr) pour affiner le cône de dérive côtier.
- Dette mineure : migrer `@app.on_event` → lifespan handler (dépréciation FastAPI).

## Session 11/07 (suite) — crash notifs, posts viraux, compteur agrandi
- **Crash photo signalement corrigé** (iteration_57 8/8 ✅) : cause = OOM
  Android (base64 pleine résolution demandé au picker). Fix :
  `src/lib/image-utils.ts::toDataUri()` (expo-image-manipulator, resize 1280
  + compress 0.7 puis base64 ≈ 100-400 Ko) ; new.tsx pickPhoto/takePhoto en
  try/catch (plus jamais de crash), avatar.ts idem (512px). Vérifié web :
  photo 1 Mo → 9 Ko stockés. Crash device à confirmer par l'utilisateur.
- **Bypass QA OTP** : header X-RateLimit-Bypass saute désormais AUSSI le
  quota 5/h par numéro (core/otp.py skip_quota, routers/auth.py). Test
  cooldown adapté (header vidé). Suites OTP 7/7.
- ⚠️ Suites pytest OBSOLÈTES (pré-existant, dû à la purge DB 10/07) :
  test_phase_b_subscription, test_phase_4_2_contacts_match,
  test_phase_4_2b_invitations, test_sprint_a2_demo_seed, test_iter19/37/47
  partiels — dépendent des comptes QA supprimés (mylene@, peer1…) ou du seed
  démo. 247 passed / 10 failed / 17 errors. → Backlog : réécrire ces
  fixtures pour créer leurs propres comptes jetables.
- **Échelles carte FIABILISÉES** (iteration_54 ✅) : cause = mesure sur le
  conteneur carré 140vmax au lieu du viewport → vpToLatLng (viewport →
  conteneur, rotation course-up incluse) + milieu = EXACTEMENT la moitié
  (fin arrondie au pas 0,2 km / 20 m). Recalcul aussi sur setBearing.
- **Crash notifications corrigé** (iteration_55 ✅) : notif → signalement
  purgé (404) = spinner infini sans retour. Désormais écran « Signalement
  introuvable » (report-not-found) + bouton Retour ; openNotif en try/catch.
- **Posts viraux Instagram/Facebook/X** (iteration_55 ✅) : rangée « Partager
  en post » sous Confirmer/Mettre à jour dans le détail (report-social-*).
  SocialPostCard 1080×1080 hors écran (react-native-view-shot) : photo/emoji,
  pill type, zone APPROXIMATIVE (0,1°) + mention « Plus de précisions sur
  SignalMar.app » ; légende copiée (Clipboard) + feuille de partage
  (expo-sharing). Web = toast « disponible sur téléphone ». À valider device.
- **Compteur de vitesse v2 « BANDE »** (12/07, iteration_58 7/7 ✅) : modèle
  « Grands chiffres » retenu puis réaffiché en bande 320×84 en haut de
  l'écran (SpeedometerOverlay réécrit). Priorité aux chiffres, unité « Nds »
  par défaut ⇄ km/h au tap (persisté sm.speedo.unit), cap à DROITE,
  fermeture croix/tap à côté, DÉPLAÇABLE par appui long 320 ms + glisser
  (RNGH Pan.activateAfterLongPress + reanimated, position persistée
  sm.speedo.pos en JSON). 3 versions de bande : A Verre / B Contraste /
  C Marine (sélecteur sous la bande).
  ⏳ EN ATTENTE : choix A/B/C par l'utilisateur → retirer le sélecteur.
- **Compteur de vitesse agrandi** (iteration_56 ✅) : tap sur la pill vitesse
  → overlay animé (SpeedometerOverlay), 3 VERSIONS au choix (sélecteur A/B/C
  intégré, persisté sm.speedo.variant) : A cadran marin SVG aiguille,
  B grands chiffres 96pt, C anneau. Fermeture : tap visuel / croix / fond.
  ⏳ EN ATTENTE : choix de la version préférée par l'utilisateur → ensuite
  retirer le sélecteur et garder la version choisie.
  ⚠️ Le testing agent a réparé 2 corruptions d'édition dans map.tsx
  (fragments orphelins fin de fichier + bloc d'état manquant) — map.tsx
  2160 lignes, découpage recommandé (backlog refactoring).

## ⚠️ TODO AVANT PUBLICATION (checklist de l'utilisateur — NE PAS OUBLIER)
1. **Bascule de comptes (DEV)** : actuellement OUVERTE À TOUS (mode dev,
   décidé le 11/07). Avant compilation/publication :
   - retirer l'option pour tous les comptes SAUF l'admin (antoninlepinay@gmail.com)
   - pour l'admin : pouvoir se connecter au compte de N'IMPORTE QUEL utilisateur
     en le cherchant par NUMÉRO DE TÉLÉPHONE
   - fichiers : backend `routers/dev_switch.py` (2 endpoints, commentaires TODO
     en place), frontend tuiles `profile.tsx` + `settings.tsx` (commentaires TODO),
     écran `profile/test-switch.tsx`, tests `test_phase_t_switcher.py` à adapter.

## Bouées IALA agrandies + bascule comptes DEV (11/07/2026 soir)
- **Compte rendu PDF du 11/07** généré (reportlab/platypus, 2 pages propres) :
  `/app/backend/public/synthese-2026-07-11.pdf`, servi par
  GET `/api/docs/synthese-2026-07-11.pdf` (route dans server.py, même
  pattern que les synthèses des 07 et 08/07). Lien vérifié (HTTP 200).
- **Visualiseur bouées** (onglet Sécurité → Bouées IALA) : intro « Touchez une
  bouée pour l'agrandir » ; tap sur une carte → modal plein écran (BuoyVisual
  165px + nom + description + feu), balayage vertical = bouée suivante
  (FlatList pagingEnabled, PAS de boucle), tap sur la page OU croix = fermeture,
  compteur « x / N » + hint en bas. testIDs : buoy-card-<id>,
  buoy-viewer-page-<id>, buoy-viewer-close.
- **Bascule comptes DEV rétablie et OUVERTE À TOUS** :
  - Backend : GET /api/dev/test-accounts liste TOUS les comptes (+ phone) ;
    POST /api/dev/switch-account prend `target_user_id` (plus target_email) ;
    plus de whitelist en mode DEV. Tests réécrits (6/6 verts).
  - Frontend : tuile « Comptes de test — bascule rapide » visible pour tous
    (profile + settings, gate isTestAccount retiré) ; test-switch.tsx affiche
    phone, switch par user_id ; AuthContext.switchToTestAccount(userId).

## Réglages — 3 correctifs UI/UX (11/07/2026 soir, iteration_52 ✅)
- Chevauchement « Zone de veille — Navigation » / « 6.5 km · 3.5 NM » corrigé
  (flexShrink sur le libellé, wrap sur 2 lignes ; AlertSettingsPanel).
- Libellé : « Nombre de répétition des alertes » (ex-« Nombre de répétitions »).
- **Règle sécurité rétablie** : au moins 1 canal actif (vibreur incompressible).
  Couper voix avec vibreur déjà coupé → vibreur auto-réactivé + toast info ;
  couper vibreur avec voix déjà coupée → REFUSÉ + toast erreur
  (toggleVoice/toggleVibration dans AlertSettingsPanel).

## P0 clavier login + Diagnostic par rôle (11/07/2026) ✅ (iteration_51 7/7)
- **Clavier login** : `react-native-keyboard-controller@1.18.5` installé
  (inclus dans Expo Go SDK 54) ; `KeyboardProvider` au root (_layout.tsx) ;
  `(auth)/login.tsx` : KeyboardAvoidingView+ScrollView remplacés par
  `KeyboardAwareScrollView` (bottomOffset 24) → le champ focalisé (dont la
  recherche parrain) reste TOUJOURS visible au-dessus du clavier.
  `scrollIntoView` supprimé ; `scrollToSponsorBox` conservé (ouverture du
  bloc sans clavier). ⚠️ Comportement clavier réel à valider sur téléphone.
- **Diagnostic par rôle** (`app/diagnostic.tsx`) : flag `advanced =
  isTestAccount(user?.email)` (whitelist test-accounts.ts, admin =
  antoninlepinay@gmail.com) désormais APPLIQUÉ au rendu. Standard : État
  système + « Envoyer par mail au support » (diag-mail) + Retour uniquement.
  Avancé/admin : + ping backend, partage .txt, upload backend, logs/filtres,
  vider les logs. Fix bonus : `router.replace("/(tabs)/map")` (3×, corrige
  l'« Unmatched Route » web + erreurs tsc préexistantes).
- Comptes créés en test : 0699887766 (TestDiag51, standard, OTP 123456).

## Session 11/07/2026 (fork) — Profil→Abonnement + bascule auto Vigie⇄Nav ✅
- **Pseudo (onglet Profil)** : clic → page Abonnement (`profile-pseudo-btn`,
  icônes diamant+chevron). L'édition du pseudo vit désormais dans Réglages :
  rangée `settings-pseudo-edit` (composant `src/components/PseudoEditRow.tsx`,
  rangée + modal) placée juste AU-DESSUS de « Se déconnecter ».
- **Page Abonnement relookée** : hero en tête (`subscription-hero`) — avatar
  104px bordure orange MODIFIABLE (tap → galerie → upload, badge caméra,
  `subscription-avatar-edit`), pseudo, pill « Membre Premium », hint
  « Touchez la photo pour la changer ». Helper partagé
  `src/lib/avatar.ts::pickAndUploadAvatar()` (utilisé aussi par l'onglet Profil).
- **Bascule AUTO Vigie ⇄ Navigation** (map.tsx) : vitesse ≥ 3 km/h maintenue
  5 s → Navigation ; < 3 km/h 5 s → Vigie. Agit UNIQUEMENT sur les TRANSITIONS
  (départ/arrêt) → un basculement manuel est respecté jusqu'au prochain
  changement d'état réel. Réglage `autoModeSwitch` (défaut ON) dans
  voiceSettings, switch en TÊTE du panneau « Zone de veille & alertes »
  (`alert-auto-mode-switch`, full uniquement). 1ʳᵉ bascule auto (flag persisté
  `sm.autoswitch.info_shown`) → bannière carte `map-autoswitch-banner` avec
  bouton « Régler » → deep-link `/profile/settings?focus=autoswitch` (scroll
  auto sur la section + rangée surlignée orange) ; bascules suivantes → toast.
  ⚠️ Non testable sur web (pas de vitesse GPS) — à valider sur téléphone.
- **Fix bloquant hérité du fork** : `friends.tsx` laissé cassé (balise
  `</ScrollView>` orpheline → bundle web en échec 500). Intégration
  `ContactNameSearch` TERMINÉE dans la modal « Ajouter un ami » : recherche
  par NOM (contacts) + recherche manuelle email/téléphone/code en dessous,
  le tout dans un ScrollView (P0 n°2 partiellement résolu — reste share-invite
  à vérifier).
- Tests : iteration_48 — 9/9 flows UI validés. Fix du testing agent intégré
  (changeAvatar/avatarUploading dans subscription.tsx).
- **Fix UX « Ajouter un ami » (retour user 11/07, iteration_49 ✅)** : personne
  sans compte SignalMar → plus AUCUNE erreur rouge ; carte jaune INVITATION
  inline (`friends-invite-card`) « X n'est pas encore sur SignalMar » +
  bouton « Inviter par SMS » (`friends-invite-btn`) → ferme la modal et ouvre
  /share-invite. Vaut pour la recherche par NOM (contacts) ET la recherche
  manuelle email/téléphone/code (état `notFound` partagé, reset entre
  recherches). Cas trouvé → carte résultat « Ajouter » inchangée.
- Explication crash user 16h32 (Expo Go) : c'était exactement la balise
  `</ScrollView>` orpheline de friends.tsx (WIP pré-fork) — corrigée à 16h51,
  aucun log nécessaire.

## Cache contacts 30 j + invitation groupe par contacts (11/07/2026) ✅
- **Cache carnet d'adresses** : `loadLocalContacts()` (contact-sync.ts) est
  cache-first — AsyncStorage `signalmar.contacts-cache.v1`, TTL 30 jours
  (`CONTACTS_CACHE_TTL_DAYS`), `{forceRefresh}` pour relire le téléphone
  (repart pour 30 j). Toutes les recherches en profitent (lecture+E.164+SHA-256
  lente sur gros carnet).
- **`ContactsRefreshButton`** (src/components) : icône contact + flèche
  « Mettre à jour » (toast succès), await onRefreshed. Placé dans :
  ContactNameSearch (droite du champ, `<prefix>-refresh`), header /share-invite
  (`referral-contacts-refresh`, natif + permission accordée), header de liste
  /groups/invite (`group-invite-contacts-refresh`).
- **Groupes — « Partager l'invitation »** (`group-share-invite`, groups/[id])
  → route vers /share-invite en MODE GROUPE (params group_name/group_code) :
  titre « Inviter au groupe », SMS = `shareGroupMessage` (code du groupe +
  lien d'affiliation + « Groupes → Rejoindre avec un code »), recherche par
  NOM + multi-sélection + SMS groupé identiques au parrainage. L'ancien
  Share sheet vit dans « Partager autrement… » (buildInviteText supprimé).
- **/groups/invite** : filtre par NOM (`group-invite-search`, nom carnet OU
  pseudo, insensible accents) + bouton refresh ; `runSync(localOverride?)`.
- **Audit points de partage — tous en recherche par NOM ✓** : parrainage
  (share-invite), parrain à l'inscription (login), Ajouter un ami (friends),
  invitation groupe SMS (share-invite mode groupe), marins déjà inscrits
  (groups/invite filtré). Échelle carte : DÉJÀ implémentée (MarineMap 10/07) —
  retirée du plan P0.
- Tests : iteration_50 — 7/7 UI web + revue statique OK. ⚠️ Flux natifs
  (cache réel, composeur SMS) à valider sur téléphone (Expo Go).

## Purge DB (10/07/2026)
- 547 comptes supprimés — il ne reste QUE l'admin (SignalMar / +33760071445 / OTP 123456).
- Whitelist Phase T + DEV_BYPASS_EMAILS réduites au seul admin (dev_switch.py, core/auth.py).
- Reports conservés (pseudo auteur dénormalisé) ; notifications/points/groupes fantômes purgés.
- Script one-shot : `/app/backend/scripts/purge_accounts_20260710.py`.
- NB : lancer la suite pytest recrée des comptes jetables `test_*@signmar.app` (normal).
0710.py`.
- NB : lancer la suite pytest recrée des comptes jetables `test_*@signmar.app` (normal).

## Post viral + ID COURT + Loupe (12/07/2026) ✅
- **short_id** : 8 caractères MAJUSCULES sans ambiguïté (alphabet sans I/L/O/0/1),
  généré à la création (`routers/reports.py::_new_short_id`), backfill paresseux
  sur lecture détail (`ensure_short_id`). 110 anciens signalements backfillés +
  index unique sparse `short_id`. Exposé dans `serialize_report` (liste + détail).
- **GET /api/reports/by-code/{code}** : résolution insensible à la casse → {id, short_id, type} ;
  404 FR si inconnu, 422 si < 4 caractères.
- **SocialPostCard** (partage Instagram/FB/X) : extrait des 100 premiers caractères
  de la description + "...", aperçu carte OSM FLOUTÉ (tuile zoom 7, coords arrondies 0,1°,
  Image blurRadius=6) et texte promo exact : « Obtenez gratuitement SignalMar sur
  SignalMar.app (Android et Iphone) et retrouvez en détail ce signalement : [SHORT_ID] ».
  Légende presse-papiers (shareSocial) mise à jour avec la même phrase promo.
- **Loupe carte** : FAB `map-search-fab` en bas à GAUCHE de la carte → modale
  (`map-search-input`/`map-search-submit`) → navigation /report/{id}.
- Tests : pytest 8/8 (tests/test_short_id_and_by_code.py) + frontend 100 %
  (login OTP, recherche code valide/invalide, détail sans crash).
- ⚠️ Capture/partage natif (view-shot + expo-sharing) à valider sur téléphone.

## Page web publique /s/[CODE] (12/07/2026) ✅
- **GET /api/public/report/{code}** SANS auth : aperçu anonymisé — coords arrondies 0,1°,
  extrait 100 car., pseudo uniquement (jamais le vrai nom/author_id), statut
  active/ended/expired, 1re photo. 404 FR inconnu / 422 < 4 car.
- **Route Expo `app/s/[code].tsx`** (publique, sans login) : pill type, méta
  « Signalé il y a X par pseudo », extrait, tuile carte floutée (approx.),
  code court, CTA « Obtenir SignalMar gratuitement » (→ landing /api/join).
  Si connecté : bouton « Voir en détail dans l'app » → /report/{id}.
- `signalMarReportUrl()` (share-app.ts) : lien /s/CODE ajouté à la légende
  presse-papiers des posts viraux (TODO release : domaine signalmar.app).
- Fix : `theme.surface` inexistant → `theme.bg2` (modale loupe map.tsx).
- Tests : pytest 8/8 (test_iter59_public_report_preview.py) + 3 flux UI ✅
  (iteration_59.json). Aucune fuite de position exacte ni de vrai nom.

## Compteur — version unique « Verre » (12/07/2026) ✅
- Sélecteur A/B/C supprimé : la bande garde UNIQUEMENT le design « Verre » (ex-A).
  `SpeedoVariant`, props `variant`/`onVariantChange`, styles B/C et persistance
  `sm.speedo.variant` supprimés (SpeedometerOverlay.tsx + map.tsx).
- Conversions VÉRIFIÉES : 1 nd = 1852 m/h → m/s×3,6 = km/h ; km/h÷1,852 = Nds
  (overlay) ; m/s×1,9438445 (= 3600/1852) = Nds (pill barre du haut). Correct.
- Vérif UI : bande ouverte, 0 bouton variante, valeur « 0.0 Nds ».

## Compteur — astuce auto-masquée + audit du cap (12/07/2026) ✅
- « Appui long pour déplacer » : visible 3 s à chaque ouverture puis fondu
  progressif 800 ms (reanimated withDelay+withTiming, hintOp). pointerEvents none.
- Audit du CAP : source GPS coords.heading (cap vrai / route fond) accepté
  uniquement en mouvement ≥ 0,6 m/s, compas trueHeading à l'arrêt (mode Nav),
  lissage EMA α=0,25 + deadband 2° avec wraparound 0/360 correct ; secteurs
  N/NE/E/SE/S/SO/O/NO index round(h/45)%8 corrects. RAS — affichage juste.
- Vérif UI web : hint visible à l'ouverture, opacity 0 après 4,5 s.

## Compteur v4 — centrage + cap 1 ligne (12/07/2026) ✅
- Ouverture TOUJOURS centrée : persistance de position supprimée (sm.speedo.pos),
  tx/ty remis à 0 à chaque ouverture ; déplacement session uniquement.
- Chevauchement interdit avec les pills du haut : clamp ty ≥ 0 au drag.
- Cap sur UNE ligne : [icône compas 19] devant + « 279° O » (valeur 21px blanc
  gras, orientation à droite après la valeur). Hauteur bande 84 → 72 sans
  réduire les chiffres de vitesse.
- Vérif UI : bande offset horizontal 0 px, compacte, cap « — » sur web (GPS N/A).

## FABs carte + drag compteur (12/07/2026) ✅
- Compteur : drag vertical élargi — la bande peut se COLLER juste sous les pills
  du haut (minTy = insets.top + 54 − ANCHOR_TOP 108) sans chevauchement ;
  clamp bas inchangé (collage bas OK).
- FABs droite : « Signaler » sorti de la colonne et décalé à GAUCHE des icônes
  (fabRow/fabCol, bottom-aligned) ; icônes rondes réduites 48/46 → 44 px
  (alertCfg, radar, nav, cône, refresh, locate). Vérifié en PAYSAGE 844×390 :
  les 5 icônes + Signaler entièrement visibles (y 54→306).

## Paysage — couloir FABs (12/07/2026) ✅
- Chevauchement cloche notifications / colonne FABs résolu : en PAYSAGE,
  paddingRight (44+16+8) appliqué au topOverlay ENTIER (pills + bandeaux)
  → couloir dédié à droite pour la colonne d'icônes. isLandscape via
  useWindowDimensions. Vérif 844×390 : bell right 760 < FABs left 784.
- ⚠️ LEÇON : ne PAS lancer plusieurs search_replace en PARALLÈLE sur le même
  fichier (map.tsx corrompu 2× par des queues dupliquées) — édits séquentiels.

## AUDIT + REFONTE DES ALERTES SONORES (12/07/2026) ✅
Audit complet demandé par l'armateur (symptômes : déclenchements ultra tardifs,
voix absentes, vibreur en retard). 8 bugs identifiés puis corrigés :
1. health lu à r.health au lieu de r.extras.health (voix animaux muette).
2. Bascule auto Vigie→Nav court-circuitait le périmètre Vigie (cône + ½ rayon).
3. Vibreur couplé à la voix (voix OFF ⇒ plus rien) — contraire à la règle.
4. Cooldown 5 min sans ré-armement à la sortie du périmètre.
5. prefetchAlertVoice jamais appelé en usage réel (latence BT/JBL).
6. Type sans texte vocal bloquait le tick sans rien jouer.
7. Deps du watcher incomplètes (cap/cône). 8. Vestige migration baseRadiusM purgé.

NOUVEAU MODULE CENTRAL /app/frontend/src/lib/sound-alert.ts (remplace
voice-alert-watcher.ts, SUPPRIMÉ). Règles VALIDÉES par l'armateur :
- VIGIE : 360°, tout le temps, rayon zoneVigieM.
- NAVIGATION : cône UNIQUEMENT + présence continue ≥ 3 s (CONE_DWELL_MS,
  anti-jitter de cap). Sans cap (nav manuel à l'arrêt) : repli 360° zoneNavM.
- VIBREUR incompressible : bannière + vibration pour TOUS types non coupés ;
  VOIX seulement types éligibles (autorités, obstacles, mammifères, blessés/morts).
- RÉ-ARMEMENT : sortie ×1,2 pendant ≥ 10 s (REARM_EXIT_MS) → ré-alerte.
- BT/JBL : préchauffage TTS à rayon ×1,3 + 300 m (PREFETCH_FACTOR/MARGIN).
- buildAlertText : healthState() normalise blesse/mort/alive_injured/dead_*.
- Logger : contrat (category, message, data) — logger.info N'EXISTE PAS.

POPUP D'ALERTE : réglages REPLIÉS par défaut ; roue dentée (map-alert-gear)
déplie UNIQUEMENT le périmètre du mode actif (AlertSettingsPanel
variant="alert" + mode) + bouton « Tous les paramètres » → /profile/settings.
⚠️ NE PAS ajouter de réglages avancés dans la popup (exigence armateur).

TESTS : 5 signalements TEST ALERTES créés dans le golfe du Morbihan
(autorites 47.5560,-2.7620 / obstacle 47.5620,-2.7800 / mammifère 47.5500,-2.7950 /
oiseau blessé 47.5460,-2.7700 / pollution 47.5580,-2.7500). Itérations 60+61 :
9/9 PASS (déclenchement à 0,8 km pour zone 1 km, popup repliée, fallback
pollution, voix oiseau blessé, ré-armement, zéro crash logger).
⚠️ À valider sur téléphone : vibreur réel, dwell 3 s du cône en navigation,
préchauffage Bluetooth JBL.

## Boutons zoom +/- (12/07/2026) ✅
- Contrôle Leaflet intégré (bottomleft) RETIRÉ ; remplacé par des boutons
  natifs RN 44 px (map-zoom-in / map-zoom-out) empilés côté GAUCHE au-dessus
  de la loupe. Handle MarineMap : zoomIn()/zoomOut() → SM.zoomIn/zoomOut
  (setZoom instantané ±1, bornes min/max). Vérifié web : zoom/dézoom OK.

## Son d'alerte au plus tôt + fiabilité courants (13/07/2026) ✅
- voice-player.ts : cache MP3 LOCAL sur l'appareil (Map 16 entrées, hash djb2,
  fichier cache mobile / objectURL web). prefetchAlertVoice télécharge
  désormais le MP3 EN LOCAL (plus seulement cache backend) → lecture
  INSTANTANÉE au déclenchement (zéro réseau, réveil BT immédiat).
  playAlertVoice : cache local d'abord ; sinon fetch avec TIMEOUT 5 s
  (AbortController) → repli TTS embarqué (expo-speech) sans délai.
- sound-alert.ts : ORDRE de déclenchement inversé → 1) VOIX (dispatch
  immédiat) 2) vibreur 3) bannière.
- Vérifié e2e web : bannière + réglages repliés OK ; /api/tts/alert cache
  backend = 13 ms.
- ⚠️ Les signalements TEST ALERTES expirent en ~6 h — re-seeder avant tests
  (un frais recréé : autorites golfe 47.5560,-2.7620, short XNVN2CQF).
- FIABILITÉ COURANTS (réponse armateur) : source Open-Meteo Marine = modèle
  SMOC Météo-France/Mercator, maille 0,08° ≈ 8 km, horaire, MAJ 24 h.
  Valeur retenue : fiable ≥ 20 km des côtes (≈ 11 NM ; 2,5 mailles) ;
  8-20 km indicatif ; < 8 km non fiable (raz/goulets/estuaires non résolus,
  ex. golfe du Morbihan). Idée en attente : indice de confiance sur les
  cônes de dérive côtiers.

## Cônes de dérive — bande côtière 20 km (13/07/2026) ✅
- core/drift.py : has_land_within_km(lat,lng,20) — 180 points (6 anneaux ×
  30 caps) via API Elevation Open-Meteo (DEM Copernicus 90 m), terre = élév.
  > 0,5 m. Détecte continent ET îles (Belle-Île, Groix, Ouessant validés).
  Cache Mongo coast_cache + mémoire (cellules ~2 km). Fail-safe « côtier »
  SANS mise en cache (rate-limit ne doit pas empoisonner le cache).
- refresh_drift_cone : si terre < 20 km → courant forcé à 0 (vent SEUL) +
  flag drift_cone.wind_only=true. Backfill exécuté : 15 cônes côtiers / 1 large.
- Front : popup Leaflet du cône (classe .sm-cone-warn, orange) : « Dérive
  estimée uniquement avec les valeurs des vents sur le secteur, utilisez vos
  connaissances des courants locaux pour affiner l'estimation de la direction
  de dérive de l'objet. » + même note dans le détail report/[id].tsx.
- BUG corrigé : MarineMap tronquait drift_cone à {polygon,distance_km} dans
  les DEUX payloads SM.setReports → bearing_deg/wind_source/wind_only ajoutés.
- Réponse armateur (îles) : la règle 20 km s'applique à TOUTE terre, îles
  comprises — autour d'Ouessant (Fromveur ~8 nds), Sein, etc., le modèle est
  précisément le plus faux ; l'échantillonnage d'élévation les détecte.

## Lot de 30 signalements TEST (13/07/2026) ✅
- seed_test_lot_30.py : Lot A = 10 golfe du Morbihan (dont fond du golfe/Séné),
  Lot B = 10 Mor Braz (golfe↔Belle-Île), Lot C = 10 au large > 20 km (dont SE
  Belle-Île). Descriptions préfixées « TEST LOT ». Expirent en ~6 h.
- Vérif bande 20 km : cônes A+B = wind_only TRUE (8/8) ; cônes C = FALSE (4/4,
  vent+courant). Les types non éligibles dérive n'ont pas de cône (normal).
- FIX : retries backoff (1,5 s puis 4 s) dans has_land_within_km — le
  rate-limit de l'API Elevation en rafale de seeds produisait de faux
  « côtier » au large (fail-safe). Espacer les seeds de 2 s reste conseillé.

## FIX GPS — plus de localisation (13/07/2026) ✅ (testé iter 62 : 4/4 PASS)
Bug terrain : aucune position affichée après plusieurs minutes, GPS actif.
2 causes racines dans map.tsx :
1. getCurrentPositionAsync BLOQUANT avant watchPositionAsync → fix à froid
   ou exception provider = chaîne GPS morte + bannière « Localisation
   refusée » à tort, sans retry.
2. Aucune chauffe GPS au lancement (uniquement au montage de la carte).
Correctifs :
- Nouveau /app/frontend/src/lib/gps-warmup.ts : startGpsWarmup() au BOOT
  (_layout.tsx) — permission, getLastKnownPositionAsync (instantané), watcher
  High 1 s immédiat, fix rapide en parallèle. started=false si refus → re-tentable.
- map.tsx : seed instantané via getWarmLocation(), watcher démarré SANS
  attendre de fix avec RETRY (40 × 3 s) ; permDenied UNIQUEMENT sur refus
  réel de permission ; getCurrentPositionAsync non bloquant en parallèle.
- Vérifié web : pill GPS en 0,5 s, updates 1 s, bannière refus OK, 0 régression.
- ⚠️ Validation finale du fix à froid : sur le téléphone de l'armateur.

## File d'alertes séquentielle par distance (13/07/2026) ✅ (iter 63 : 3/3 PASS)
Bug terrain : 2 signalements dans le périmètre → seul le 1er alertait (le 2e
était marqué « alerté » mais sa voix était sautée par le verrou voicePlayingRef,
jamais rejouée à cause du cooldown).
Fix sound-alert.ts : FILE hiérarchisée par DISTANCE (QueuedAlert[]) — tous les
candidats sont enqueués (cooldown à l'enqueue), processQueue les joue UN PAR UN
(bannière + vibreur + voix), le plus proche d'abord ; attente de fin estimée de
la phrase (min(12 s, 1500 + 70 ms/caractère)) + 800 ms entre deux alertes.
voicePlayingRef supprimé. Vérifié : séquence autorité (330 m) → conteneur
(600 m) → mammifère (667 m) en ~16 s, ordre strict, 0 erreur console.
3 signalements TEST FILE créés près de 47.50,-2.90 (expirent ~6 h).

## Lot D — 10 dérivants au large de Brest + validité 48 h (13/07/2026) ✅
- 3 signalements TEST du fond du golfe SUPPRIMÉS (Séné/Conleau : estran/terre —
  interdit ; le DEM 90 m les voyait à 0 m, d'où le passage du geofencing).
- Lot D (seed_lot_d_brest.py) : 10 signalements DÉRIVANTS en mer d'Iroise /
  large Brest, 30-60 km de toute terre (Ouessant/Molène/Sein évitées).
  Types éligibles dérive uniquement (conteneur, ofni, oiseau mort) — les
  pollutions (hydrocarbures/dechets) ne sont PAS éligibles au cône.
  10/10 cônes VENT+COURANT (wind_only=False), vent AROME 1.3km,
  caps de dérive ~320°-12° (vers N/NO). Faux « côtier » D-Large NO corrigé
  (rate-limit) par recalcul.
- Validité 48 h appliquée aux 45 signalements TEST (matin + lot D) →
  expirent le 15/07 ~11:24 UTC.

## V2 Navigation — Lot du 22/07/2026 (fork) ✅ (en test)
Retour armateur (Msg 393) traité en bloc :
1. **Routage 2 passes** (core/routing.py + bathy.py `window(pool=True)`) :
   décimation MAX-POOLING (les chenaux étroits survivent) → passe grossière
   MAX_DIM=520 puis RAFFINEMENT tronçon par tronçon (FINE_DIM=420, retry
   fenêtre élargie). Fix « Aucune route sûre » Belle-Île ↔ Golfe (41 km OK
   en ~1 s, testé les 2 sens, marges 10 et 50 m).
2. **Marge latérale min 50 → 10 m** (défaut 10) : boat-settings.ts, boat.tsx,
   RouteIn (ge=10), core LATERAL_MIN.
3. **Route bloquée ≠ effacée** : RouteError(payload {blocked_at,
   partial_waypoints}) → 422 ; front garde la route, affiche cercle rouge
   pulsant + tronçon atteignable gris (leaflet __setBlocked, state `blocked`).
4. **Virages arrondis** : _round_corners iterations 2→3.
5. **Perf WMS tablette** : bounds par couche SHOM (plus de requêtes MED/Corse
   en Bretagne), keepBuffer 6, updateWhenIdle, updateWhenZooming=false.
6. **Route manuelle** : « Créer une route » → choix auto/manuelle/enregistrées.
   Manuelle : point du menu = départ, appui long = étapes (tracé teal numéroté
   __setDraftRoute), barre Annuler/Retirer/« Créer cette route » →
   POST /api/routes/manual (distance+profil) → RouteCard (mode manual).
7. **Routes enregistrées (max 20/user)** : POST/GET/DELETE /api/routes/saved
   (collection saved_routes, id uuid). UI : dialogue nom après création
   manuelle, bouton bookmark RouteCard, menu tracé, liste (charger/supprimer).
8. **Balises cliquables** : GET /api/bathy/seamarks?bbox → overlay tap
   invisible Leaflet (zoom ≥12) → fiche FR (type IALA, côté, couleur, feu).

## Lot armateur du 22/07/2026 (zip elements.zip) ✅ validé iter98 + fix asymétrie
1. **DANGERS OSM ingérés** (scripts/ingest_hazards.py → data/bathy/hazards.json :
   623 roches + 76 épaves). Moteur A* les ÉVITE (seamarks.py hazard_blocks :
   roches TOUJOURS ; épaves seulement dangereuses/profondeur inconnue —
   choix armateur ; obstructions idem ; R_HAZARD_M=60).
2. **Redressement global + réparation** (routing.py) : _corridor_safe (5 lignes
   parallèles pleine résolution + écart mini aux balises/dangers),
   _straighten (string pulling), _round_pts (Chaikin contrôlé),
   _repair_segments (re-résolution step≈1 des segments douteux),
   _snap_fullres (extrémités jamais sur estran). Fix « écart injustifié »,
   « route débile », « route sur roche semi-couvrante », min_depth ≥ seuil
   partout. Fix asymétrie aller/retour : micro-tronçons <150 m fusionnés +
   cibles intermédiaires infranchissables SAUTÉES dans le raffinement.
3. **Carte** : UNE seule couche WMS SHOM à la fois (_syncBathy — fix flashs/
   superpositions tablette) ; OpenSeaMap maxNativeZoom=18 (fix balise disparue
   au zoom 19) ; opacité par CHIPS 30/50/70/85/100 % (le slider ne répondait
   pas dans la popup tablette).
4. **Route manuelle** : points DRAGGABLES (dragend → draft_move → RN).
5. **Dangers cliquables** : /api/bathy/seamarks renvoie aussi rocks/wrecks
   (water_level, depth_m) → fiche FR avec ⚠ Danger.
6. **MP3 écart de route** fourni par l'armateur → assets/sounds/route_deviation.mp3
   (ROUTE_DEVIATION_ASSET câblé dans alert-sound.ts).
NOTE testing : testID du bouton bathy = `map-bathy-toggle` (tap court toggle,
appui long popup opacité). Rapports : iteration_96.json (iter97),
iteration_97.json (iter98).

## Marée intégrée au routage (GO armateur, 22/07/2026) ✅ validé iter99
- core/tides.py : _series_above_zh (série horaire Open-Meteo ≈ / ZH, cache
  6 h/port), _interp_at, tide_window(lat,lng,start,hours) → {port,
  height_start_m, height_min_m, window_h}.
- routers/routing.py RouteIn : + use_tide (bool, défaut false),
  departure_ts (epoch s, None = maintenant). Fenêtre = distance vol
  d'oiseau ×1.3 / 8 km/h + 30 min (1-12 h), hauteur MINIMALE retenue
  (conservateur). Échec réseau → marée basse + warning.
- core/routing.py compute_route(tide_m) : seuil carte = tirant + marge -
  marée (clamp ≥ -3 : découvrantes passables à PM). Roches/épaves
  dangereuses évitées QUELLE QUE SOIT la marée. Warning « UNIQUEMENT grâce
  à la marée » si min_depth_m < seuil marée basse. Réponse : tide_m + tide{}.
- Front : chips « Marée : Sans / Départ maintenant / +2/+4/+6 h » dans la
  barre route auto (testID route-tide-off/0/2/4/6, défaut 0) ; RouteCard
  ligne « Marée intégrée : +X,X m » (route-tide-info) + disclaimer Open-Meteo.
- Rapport : iteration_98.json (backend 5/5, frontend 2/2).

## Lot armateur du 23/07/2026 (msg 325) ✅ validé iter100 + e2e Playwright
1. **PROXY-CACHE TUILES backend** (routers/tiles.py, déjà créé) désormais
   CBLÉ dans leaflet-html.ts : buildHtml(center, zoom, crosshair, apiBase)
   → couches SHOM = /api/tiles/shom/{atl|gdl|corse|morbihan}/{z}/{x}/{y}.png
   et seamark = /api/tiles/seamark/... (fallback openseamap si apiBase vide).
   Prefetch seamark aussi via proxy. Cache disque backend + HTTP 30j/7j →
   fluidité tablette, plus de flashs (tuile téléchargée UNE fois).
2. **BUG OPACITÉ SHOM résolu & vérifié e2e** : chips 30-100 % → opacité de
   la couche passe bien (vérifié DOM iframe 0.7→0.3 + captures avant/après).
3. **SUIVI DE ROUTE** : bouton « Suivre cette route » (RouteCard,
   testID route-follow-start) + « Suivre la route » dans le menu du tracé
   (route-menu-follow). Panneau RouteNavPanel en haut (route-nav-panel) :
   cap à suivre/cap actuel/vitesse (+ vitesse croisière), distance & temps
   au prochain WP (route-nav-next), arrivée + ETA (route-nav-end), stop
   (route-nav-stop). route-guard.ts : routePosition + projLat/projLng,
   routeNavProgress() (passedIdx MONOTONE via passedIdxRef). Carte :
   __setRouteProgress → tronçon parcouru GRIS par-dessus le rouge +
   waypoints intermédiaires (petits ronds, ≤200) grisés au passage.
   Arrivée <25 m → toast + arrêt auto du suivi.
4. **CORRIDOR DYNAMIQUE** : l'alerte d'écart utilise dynamicCorridorAt(
   segIdx, route.corridor_m) quand mode="dynamic" (sinon seuil manuel).
5. **ALARME DE MOUILLAGE** (choix armateur : carte ET réglages) : bouton
   ancre FAB (map-anchor-toggle, MaterialCommunityIcons) → modal pose/levée
   (anchor-drop / anchor-lift) + rayon 5-100 m défaut 15 (AnchorPanel,
   contrôlé sur la carte, autonome dans Réglages accordéon
   settings-family-anchor). Ancre + rayon persistés (anchor.ts). Cercle
   teal + icône ⚓ sur la carte (__setAnchor), ROUGE pulsant si dérive.
   Hors rayon → anchor_alarm.wav + vibration répétés 15 s + bannière rouge
   (anchor-alarm-banner : Couper le son / Lever l'ancre). Réarmement <80 %
   du rayon. Vérifié e2e (dérive simulée 44 m → alarme → levée OK).
NOTE testing : auth e2e web = minter un JWT via core.auth.make_jwt puis
localStorage signmar.token (JSON.stringify) + retry goto /map (le 1er
hydrate peut être avorté par le reload du bundle dev et purger le token).
OTP rate-limited (429 ~50 min) si spam. Rapport : iteration_100.json.

## Lot débogage armateur 22-23/07 (zips ALL_DEBUGGING_22.07) ✅ iter101 16/16
1. **ROUTE SUR TERRE / dangereuse (vidéos 094435 vs 065903)** — causes :
   (a) le MNT SHOM 20 m donnait de l'EAU sur des îlots (Er Lannic 0,4-3,6 m !)
   → scripts/ingest_islands.py : polygones OSM place=island|islet rasterisés
   → land_mask.npy + cellules passées à NaN DANS bathy_morbihan.npy (original
   sauvegardé bathy_morbihan_orig.npy, ré-exécution idempotente) ;
   (b) plancher marée −3 m ouvrait les vasières à PM → plancher −2,5 m
   (chenal de Vannes −1..−2,2 m reste passable à PM, hautes vasières jamais) ;
   (c) règle armateur BALISAGE STRICT : mauvais côté d'une latérale interdit
   jusqu'à 200 m LÀ OÙ fond < tirant+marge+2 m (eau profonde tolérée — cas
   Teignouse validé), exemption <500 m du départ/arrivée (entrées de port),
   _wrong_side_depth() échantillonne le côté interdit ; (d) demi-couloir de
   redressement min 25 m (« trop proche côtes »).
2. **MARÉES FAUSSES (réf. maree.info 104/106/107)** — core/tides.py :
   calibration PAR PORT h = A×openmeteo_msl(t−retard)+B, base Port-Navalo
   pour tout le Golfe (PORT_CAL : PN 40/45min A1.0 B3.44 ; Arradon
   148/138 A0.81 B1.91 ; Vannes 150/145 A0.77 B2.07 + rattachés approchés ;
   génériques : +40/45 min, ZH ×1,25). Vérifié : PM Arradon 13:33/2,23 vs
   officiel 13h30/2,24. La série routage (_series_above_zh) applique la même
   correction (tide_window lit à t−retard) → marée de route du Golfe juste.
3. **Balises qui disparaissent** — tiles.py : 2 tentatives amont, repli tuile
   PÉRIMÉE si échec, tuile blanche en no-store (plus de blanc caché 60 s).
   Bathy updateWhenIdle:false (proxy rapide → plus de trous pendant le pan).
4. **Scintillement carte (alarme mouillage)** — payloads routeProgress/anchor
   MÉMOÏSÉS dans map.tsx (avant : réinjection JS Leaflet à chaque render).
5. **Slider rayon mort dans la popup carte** — cause racine : Modal Android =
   fenêtre native séparée → GestureHandlerRootView LOCAL dans le Modal +
   backdrop Pressable en FRÈRE (plus d'ancêtre qui vole le Pan). (Le vieux
   bug « curseur opacité » avait la même cause.)
6. **Waypoints grisés à tort** — franchissement seulement si offRouteM ≤ 100 m
   (sinon progression gelée), passedIdx reste monotone.
7. **Boutons zoom FIXES haut-droite** sous la cloche notifs (offset si panneau
   suivi/bannière mouillage) ; DraggableZoomButtons SUPPRIMÉ (user.zoom_btn_pos
   ignoré côté back, champ inoffensif). testID map-zoom-in/out conservés.
8. **Réglages : accordéons tous repliés par défaut** ; **Profil : rangée « Mon
   bateau » supprimée** (doublon avec Réglages). /profile/boat existe encore.
9. Bypass testeur départ à terre VÉRIFIÉ OK (fallback Arradon) — l'échec de la
   vidéo 104628 venait du blocage destination (corrigé par 1./3.).
Backlog reporté V2.x : journal de bord automatique du suivi (accepté user).
Hitbox route-nav-stop élargie 44px (P3 iter101).

## Iter103 — 22/07 soir : « Je ne peux faire AUCUNE route ! » (vidéo armateur) ✅ 43 tests verts
Reproduit e2e (compte armateur, marée réelle) : 7/7 routes domicile→côte locale échouaient.
4 causes racines corrigées (core/routing.py, core/seamarks.py) :
1. **Fenêtre A* trop petite** : le détour nécessaire (sortie du Golfe par
   Port-Navalo) sortait de la bbox départ→arrivée → escalade de fenêtres
   (pad_frac 1.2 puis 2.5) avant de conclure au blocage.
2. **Arrivée estran/poche isolée** : destination non navigable → arrivée
   ACCROCHÉE à l'eau navigable ATTEIGNABLE depuis le départ (nearest_reachable,
   fenêtre large, ≤ 5 km) + warning « arrivée déplacée (~X m) » + champ
   end_snapped. Poches MNT (bassin du Crouesty isolé) gérées. Refus honnête
   au-delà de 5 km. Filets : chemin partiel accepté si blocage ≤ 5 km du but
   (passes 1 ET 2), queue de route retaillée (≤1,5 km) si profil final trop haut.
3. **Sens conventionnel IALA faux dans les chenaux étroits** (gradient «
   distance au large » à 121° pour un chenal à 25°, chenal de Vannes FERMÉ par
   son propre balisage) : D déduit du COUPLE rouge/verte (_pair_of ≤350 m,
   règle IALA A), quinconce corrigé par projection ⊥ à l'axe des balises du
   même côté (_same_side_axis ≤600 m) ; COULOIR LIBRE garanti entre chaque
   couple (disque 45 % de l'écartement, jamais re-creusé sur un danger) ;
   STRICT 200 m réservé aux couples ET à la maille fine ≤35 m (la passe
   grossière = connectivité ; sécurité re-vérifiée pleine résolution).
4. **Waypoint grossier dans une poche d'exclusion fine** → BACKTRACKING
   (recul 2/3/5 waypoints puis nouvelle tentative grande fenêtre).
+ LOG systématique des échecs de calcul (routers/routing.py) pour diagnostic à
distance. Tests : tests/test_iter103_route_partout.py (14) + island mask
(sémantique mosaïque : le masque le plus fin fait foi) + iter96/102 mis à jour
(nouveau contrat « arrivée déplacée », borne distance goulet, test marée-agnostique).
⚠️ RESTE CONNU : land_mask_atl100 + bake îles atl100 DÉCALÉS (~1 km, produits
par l'ingestion interrompue 429) → À RÉGÉNÉRER pendant l'ingestion Overpass de
demain (P0). Sans impact zone pilote (la grille fine 20 m gagne dans la mosaïque).
Dette tests legacy (39 échecs pré-existants hors routing : seeds démo,
parrainage/abonnement, preview publique, contacts) → backlog maintenance.
Infra : backup MongoDB quotidien (scripts/backup_db.sh + boucle FastAPI,
rotation 7 j, /app/backups) ; cause « Hors-ligne » = ancienne URL preview
(fork) + hibernation preview — rescanner le QR code.

## Iter104 — 23/07 : « Toujours impossible de créer une route automatique » (2e vidéo armateur) ✅
Cause racine (reproduite via logs backend : 4 échecs no_route depuis Arradon) :
la MARGE LATÉRALE BATEAU de l'armateur = 260 m fermait TOUS les chenaux du
Golfe (< 2×260 m de large) → no_route systématique ; à marée basse le départ
Arradon lui-même devenait start_blocked.
**Fix (routers/routing.py)** : RELAXATION AUTOMATIQUE de la marge latérale par
paliers (÷2, plancher 10 m) sur no_route/start_blocked/end_blocked. Tirant
d'eau + marge de fond restent STRICTS. Route annonce la réduction (warning
« marge latérale réduite X m → Y m » + champ lateral_margin_used_m). À
l'épuisement des paliers, l'erreur de la marge DEMANDÉE est relevée
(sémantique historique : fallback testeur start_blocked préservé). Les 4
destinations de la vidéo passent (relax 260→130 m). Tests :
tests/test_iter104_lateral_relax.py (6).

### Routes longues Brest → La Rochelle (2 bugs moteur corrigés, core/routing.py)
1. **Trim d'arrivée** : la boucle « recul d'arrivée ≤1,5 km » décrémentait le
   budget APRÈS le pop → sur route longue (waypoints espacés 60+ km), un seul
   pop amputait 300 km et livrait une route tronquée annoncée « arrivée
   déplacée à 296 km » ( !). Fix : `if seg > budget: break` avant le pop.
2. **Dernier recours passe 2** : l'offset end_snapped était calculé sur le
   POINT DE BLOCAGE au lieu de l'extrémité réelle du tracé → garde ajoutée
   (d_end ≤ END_SNAP_MAX_M sinon no_route honnête).
Résultat : Brest → La Pallice/La Rochelle = 377,6 km, 30 wp, 71 s, OK.
⚠️ Limite connue : arrivée DANS un port masqué (NaN) de la grille 100 m
(vieux port LR) à marée haute → no_route honnête avec point de blocage
affiché (taper juste à l'extérieur du port fonctionne). Amélioration
possible avec secteurs TANDEM 20 m futurs.

### Ingestion Atlantique VÉRIFIÉE (état post-fork)
- land_mask_atl100 + bake îles atl100 RÉGÉNÉRÉS et ALIGNÉS (rapport :
  853 îles nommées vérifiées, 0 échec majeur, seuls des îlots < 150 m sous la
  résolution 100 m). Le « décalage ~1 km » noté en fin d'iter103 est RÉSOLU.
- seamarks.json (21:28) + hazards.json (21:36) régénérés via overpass.py.

### Dette tests legacy ASSAINIE : 39 → 0 échecs (574 passed, 3 skipped)
- iter95/97/98 : nouveaux contrats (arrivée snappée = 200 ; 422 réservé aux
  destinations sans eau ≤ 5 km — déplacées vers les terres de Vannes).
- iter103 e2e : plage de Damgan à marée réelle < 1 m = 422 LÉGITIME (5 km de
  vasières) → tests tide-aware (les 2 issues acceptées documentées).
- iter47 : baseline abonnement admin (35 mois réels gagnés ≠ 0 au rollout) ;
  test parrainage rendu déterministe (purge du compte filleul avant le flow).
- phase_t switcher : whitelist post-purge 10/07 = admin only → tests standard
  attendent 403.
- iter59 preview publique : code en dur purgé → fixture crée SON signalement.
- iter90 : id de report en dur purgé → test round-trip autonome.
- seed_demo_reports.py : short_id assigné DÈS l'insertion (la liste renvoyait
  short_id:None) + re-seed 30/30 démos.

### Frontend E2E validé (testing agent, iteration_103.json) 5/5
- Route auto depuis la carte : OK (2 s, 15,9 km, polyline rouge pointillée).
- Pointillé « arrivée déplacée » : polyline orange #F4A261 '3 8' + cercle
  creux + étiquette « reste 2,3 km à vue » rendus ; warnings RouteCard OK.
- Astuce e2e réutilisable : JWT injecté dans localStorage `signmar.token` ;
  menu « Position choisie » via `window.map.fire('contextmenu', …)`.

## Iter106 — 23/07 : marge latérale AUTO + visibilité du point de blocage ✅
Contexte : le 260 m venait du RÉGLAGE « Mon bateau » stocké sur le téléphone
de l'armateur (aucune valeur en dur dans le code — vérifié git + grep).
L'armateur l'a repassé à 50 m (confusion avec l'écart de route).

### 1. Mode AUTO de la marge latérale (défaut pour tout le monde)
- Backend : `lateral_margin_m` OPTIONNEL (None = AUTO → plancher sécurité
  10 m + attraction milieu de chenal = marge réelle adaptée à la largeur).
  Constante AUTO_LATERAL_M, log `lat_m=X(auto|manuel)`.
- Frontend : `marginMode: "auto"|"manual"` (défaut auto) dans
  boat-settings.ts (clé sm.boat.margin_mode) ; toggle 2 chips dans
  Réglages → Mon bateau (champ valeur visible en manuel seulement) ;
  map.tsx n'envoie lateral_margin_m QU'EN manuel.
- Relaxation : part TOUJOURS de la valeur configurée (manuel) ; en auto
  aucun palier (déjà au plancher). Warning relax → « réglable dans
  Réglages → Mon bateau ». Tests : tests/test_iter105_margin_auto.py (6).

### 2. BUG RACINE « je ne vois pas la zone sur la carte » (src/api/client.ts)
`request()` jetait `new Error(msg)` SANS attacher le détail structuré du 422
→ `blocked_at`/`partial_waypoints` étaient PERDUS → le point de blocage ne
s'affichait JAMAIS (depuis toujours). Fix : `err.detail` + `err.status`
attachés à l'erreur. C'est ce bug qui masquait le marqueur rouge à l'armateur.

### 3. UX blocage (map.tsx + leaflet-html.ts + routers/routing.py)
- Carte PERSISTANTE « Passage impossible » (remplace le toast 3,5 s) avec le
  message enrichi backend : réglages en cause (tirant d'eau + marge de fond,
  « marge latérale déjà réduite au minimum ») + bouton « Régler Mon bateau »
  (router.push /profile/boat) + croix de fermeture.
- Recadrage GARANTI de la carte : fitBounds(tronçon + point de blocage)
  (padding 70, maxZoom 14) sinon flyTo zoom ≥ 12 ; étiquette rouge
  « Blocage ici » sous l'anneau pulsant.
- E2E navigateur validé (2 scénarios) : blocage terres de Vannes → carte +
  recadrage + navigation Mon bateau OK ; route auto Golfe (47.50,-2.93) →
  15,9 km, marée intégrée, AUCUN blocage.
- Suite pytest complète : 575 passed / 0 failed.
⚠️ Noté (hors scope, pré-existant) : bannière « Écart de route — 47 km du
corridor » s'affiche dès le calcul quand la position GPS est loin de la
route (planification à la maison) — bruyant, à filtrer un jour (n'alerter
qu'en mode suivi ?).

## Iter107 — 23/07 après-midi : vidéos armateur (429, déconnexions, sauts carte, tests sur terre)
Sauvegarde : /app/backups/mongo_20260723_0935.tar.gz (anciennes écrasées).
Code poussé sur GitHub par l'armateur avant ces changements.

### Causes racines identifiées (2 vidéos + logs)
1. « Erreur 429 » fréquentes : l'INGRESS de la plateforme limite les rafales
   par IP (tuiles /api/tiles + polling simultanés). Le backend lui-même ne
   renvoyait AUCUN 429 à l'armateur (70 355 tuiles → 200).
2. « Déconnexions à répétition » : AuthContext purgeait le token sur TOUTE
   erreur de /auth/me (dont 429 ingress/réseau) → logout brutal à l'ouverture.
3. « Sauts dans le Golfe » : la WebView Android est rechargée (mémoire) →
   Leaflet repartait sur DEFAULT_CENTER (47.46,-2.92 = large Golfe).
4. Signalements de test sur la terre ferme : 282 artefacts pytest accumulés
   (TEST_iter90 Rennes, TEST_authorities Marseille, iter5 obs…) car le
   nettoyage échouait : DELETE auteur-only (admin → 403) + quota 1/7j (429).

### Correctifs
- client.ts request() : GET réessayés 2× (backoff 700/1800 ms) sur
  429/502/503/504 → plus de bascule « hors-ligne » sur une rafale.
- AuthContext : cache profil (signmar.user_cache) après me()/login ; purge du
  token UNIQUEMENT sur 401 ; erreurs transitoires → session conservée (cache
  ou retry 1×). signOut nettoie le cache.
- MarineMap : lastViewRef (event 'move' + zoom) ; à 'ready' d'une WebView
  RECHARGÉE → SM.setView(dernière vue, sans animation) au lieu du centre par
  défaut ; flyTo(GPS) seulement au tout premier chargement.
- leaflet-html : SM.setView ajouté (instantané + pause recentrage 5 s).
- Écart de route : alerte UNIQUEMENT si navFollow (« Suivre cette route »).
- Bandeaux du haut (welcomeCard, newBanner, autoSwitchCard) : couloir libre à
  droite (marginRight 44+md+sm) → plus de chevauchement avec la colonne zoom.
- report/[id] : 404 → removeReportFromCache(id) (marqueur fantôme purgé).
- Backend reports.py : dev/admin peuvent supprimer N'IMPORTE QUEL signalement
  (modération) → les nettoyages de tests fonctionnent désormais.
- DB : 282 artefacts supprimés (terre + hors zone + is_test + TEST_/iterN).
  Restent 71 reports dont 30 démos et 41 « réalistes » de l'armateur.
Note : « Cannot connect to Metro » dans les logs diagnostic = preview Expo
(pod hiberné), pas un bug app.

## Iter108 — 24/07/2026 : Carte & navigation (suite vidéos armateur)

### Causes racines identifiées (expliquées à l'armateur avant code)
1. « Itinéraires différents au même moment » : departure_ts = time.time() à
   la seconde près → hauteur de marée légèrement différente à chaque appel →
   cellules limites navigable/bloqué basculent → tracé A* différent.
2. « Balises qui disparaissent » : rafales de tuiles (pan/zoom + prefetch
   ~200 requêtes d'un coup) → 429 ingress → tuiles seamark vides.
3. 429 login : AUTH_LIMIT 5/5min par IP trop strict derrière l'ingress.

### Correctifs
- routers/routing.py : dep arrondi au pas de 600 s → routes DÉTERMINISTES
  (2 demandes identiques dans la même fenêtre de 10 min = même tracé).
  Vérifié : waypoints strictement identiques sur 2 appels successifs.
- leaflet-html.ts : attachTileRetry (backoff 1/2/4 s + cache-buster sur les
  retries) sur OSM, seamark (4 retries) et couches SHOM ; prefetch lissé via
  file d'attente (1 tuile/60 ms, bornée à 400) au lieu du burst.
- core/rate_limit.py : AUTH_LIMIT 5→20/5min, GOOGLE_SESSION_LIMIT 10→20/5min.
- MarineMap.tsx : lastKnownView au niveau MODULE (survit au remontage du
  composant, pas seulement au reload WebView) + HTML initial construit sur
  la dernière vue connue → plus de saut vers le Golfe.
- map-styles.ts : couloir zoom (44px+marges) appliqué à newBanner (était
  marginHorizontal:0 pleine largeur) et introBannerWrap (intro cône).
- DB : 3 signalements de démo restants À TERRE supprimés (Belle-Île/Hoedic :
  40014394…, 1ff784b3…, eca35498…). Restent 68 reports, tous en eau (depth
  grid non-NaN vérifié sur toute la collection).

### Tests (iter108, /app/test_reports/iteration_105.json)
- Backend 17/17 PASS (déterminisme, non-régression tide/margin, tuiles,
  rate-limit, 404 des 3 supprimés). Frontend : tuiles seamark 25/25 en 200,
  zoom non chevauché par les bandeaux, 0 erreur console.
- Nouveau : /app/backend/tests/test_iter108_route_determinism.py.

### Reste à faire (backlog)
- Profil de navigation (côtier / chenaux étroits / large) → marges auto (P3,
  explicitement gardé pour plus tard par l'armateur).

## Iter109 — 24/07/2026 : COMPAS DE MESURE (demande armateur)

### Contexte
L'armateur veut auditer en profondeur la navigation (distances routes/objets/
obstacles). Le plan de correction des marges latérales (dangers = marée basse,
tampon autour des roches, marge souple, transparence marge min) est GARDÉ DE
CÔTÉ — il y réfléchit, on le reprend après le compas. Le déplacement du
réglage marge latérale (Mon bateau → Navigation & routes) fait partie de ce
lot en attente.

### Fonctionnalité livrée
- Compas de mesure type « compas de marine » : segment A→B avec épingles
  déplaçables, ligne pointillée ambrée, carte flottante distance + relèvement
  vrai (A→B, 3 chiffres).
- Distance au mètre près : mètres par défaut (< 1 km), km à 3 décimales
  au-delà ; TAP sur la carte de mesure → bascule m ⇄ NM (3 décimales,
  0,001 NM = 1,85 m).
- MAGNÉTISME (seuil 30 px) pendant le maintien : bateau, balises + roches/
  épaves/obstructions (marks /api/bathy/seamarks), signalements, tracé de la
  route (point PROJETÉ sur segment). Indication visuelle teal + haptique
  (postMsg measure_snap → Haptics RN) ; l'aimantation s'applique au dragend.
- Extrémité lâchée sur le BATEAU → aimantée : suit le GPS en temps réel
  (hook dans SM.setUser → __msBoatTick), mention « aimanté au bateau —
  mesure en direct ». Reprendre l'épingle détache l'aimant.
- Côte non aimantée pour l'instant (choix armateur, option grille SHOM ~20 m
  proposée plus tard).

### Réorganisation boutons (demande armateur)
- Cloche orange « Zone de veille » (map-alert-settings) DÉSACTIVÉE ({false &&},
  code conservé) — réglage toujours accessible ailleurs.
- Recentrage déplacé SOUS les boutons de zoom (colonne fixe haut-droite).
- Compas de mesure tout en bas de la colonne droite (halo ambré quand actif).

### Pièges techniques appris (NE PAS REFAIRE)
- Pendant un drag de marker Leaflet : NI setLatLng NI setIcon (setIcon
  remplace le DOM → le Draggable meurt en plein geste). Utiliser une classe
  CSS (sm-ms-snap) sur pin._icon pour l'état d'accroche.
- Le HTML Leaflet est un template literal TS : pas de backticks ni de dollar-accolade dans
  le JS injecté.

### Fichiers
- frontend/src/components/marine-map/leaflet-html.ts (bloc compas + CSS)
- frontend/src/components/MarineMap.tsx (props measure/onMeasureSnap)
- frontend/app/(tabs)/map.tsx (bouton, réorg), src/screens/map/map-styles.ts

### Validé e2e navigateur
Toggle, drag A/B, m⇄NM (99,287 km → 53,611 NM), snap sur signalement, aimant
bateau + mise à jour dynamique (47,7 → 43,8 km quand le bateau bouge).

### En attente (à reprendre ENSUITE, ordre armateur)
1. Plan marges latérales (5 points, voir Iter108/discussion 24/07) + déplacer
   le réglage marge latérale vers Navigation & routes.
2. Idée notée : niveau de détail carte au choix user (accélérer chargement).
3. P3 : profils de navigation (côtier / chenaux étroits / large).

### Iter109b — retouche affichage compas (retour armateur, validé e2e)
- Ligne PLEINE ambrée (pointillés supprimés), épaisseur 3.
- Placement par défaut : A(38%,56%) → B(62%,44%) de l'écran → tient toujours
  sur ≤ moitié de l'écran quelle que soit l'échelle.
- > 1 km : 2 décimales. Données sur UNE ligne : « 1,72 km - 096° ».
- PIÈGE : une édition avait laissé un doublon en fin de leaflet-html.ts
  (SyntaxError 2239) → écran blanc ; corrigé, toujours vérifier la fin du
  fichier après édition de ce gros template literal.

## Iter110 — 24/07/2026 : lot évolutions & correctifs armateur (TESTÉ 19/19 backend + e2e front)

### Clarifications armateur (SPEC IMPORTANTE — marges latérales)
- La marge latérale ne concerne QUE le plan horizontal : distance aux
  OBSTACLES (roches immergées/émergées, balises, épaves, chenaux étroits).
- La profondeur ne dépend QUE du bateau (tirant d'eau + marge de fond) et des
  hauteurs d'eau de la carte. Deux contraintes indépendantes.
- Mode actuel = PROFESSIONNEL. Évo prévue : mode DÉBUTANT (respect impératif
  des chenaux balisés entrée/sortie de port + passages des cardinales),
  bascule dans réglages navigation. NE PAS développer sans GO armateur.
- Le plan marges (5 points) reste EN ATTENTE de la réflexion armateur ;
  inclut le déplacement du réglage marge latérale vers Navigation & routes.

### Livré
1. Route manuelle : plus de popup d'enregistrement à la création (toast +
   bouton « Suivre cette route » ; enregistrement via tap sur le tracé).
2. Signalement « Autre » : sous-type « Description libre » pré-sélectionné +
   focus auto sur le champ commentaire (commentRef, new.tsx).
3. Nouveau type « meteo » (Phénomène météo — #5C7CFA, icône thunderstorm,
   TTL 120 min) : orage_proche, trombe_marine, brume_mer (non dérivants).
   Obstacles : + embarcation_derive (V6/C4) et nappe_sargasses (V3/C7),
   DÉRIVANTS (cône). Miroirs backend : server.py (REPORT_TYPES, Literal,
   TTL_OVERRIDES, COLORS/ICONS partage), core/drift.py, leaflet TYPE_ICON.
4. HAUTEUR D'EAU au clic court : GET /api/bathy/depth?lat&lng →
   {depth_zh_m, tide_m, height_now_m, port} ; convention MNT : d<-7 = terre,
   height_now<=0 = « à sec (découvert) ». Leaflet map.on('click') →
   postMsg map_tap (ignoré si cône/balise/route/compas consommait le clic,
   ou pendant la route manuelle) → carte flottante water-info-card.
   Nature des fonds : PAS dans l'open data ingéré → repli validé armateur.
5. ROUTES DOUTEUSES : auto no_route avec tronçon partiel → 422 +
   detail.fallback_route {waypoints=partiel+destination, compromised_from,
   distance_m} → front crée la route risk:true avec tronçon ROUGE (#FF1744)
   + label « ⚠ passage compromis ». Manuelle : compromised_legs[] (échantillon
   par segment, terre/fond<seuil) + risk:true côté backend ET client (défense
   en profondeur). SUIVI : startFollow → modal acceptation du risque
   (risk-accept / risk-cancel) obligatoire si route.risk.
6. Anti-disparition DÉFINITIF : scripts/preseed_tiles.py — pré-chargement de
   64 513 tuiles seamark (Bretagne Sud z11-16 + cœur Golfe z17) dans le cache
   disque du proxy. Lancé en tâche de fond (preseed.log, ~1h, reprise sûre).
   Réponse armateur : téléchargement sur mobile PAS nécessaire ; vrai
   hors-ligne device = build natif (évo possible).

### Bug trouvé par testing agent & corrigé
- manual_route ne posait pas risk:true quand compromised_legs non vide →
  le modal de risque était contourné. Fix : core/routing.py + double
  sécurité dans map.tsx (setRoute risk dérivé de compromised_legs).

### Tests
- Backend 19/19 (nouveau /app/backend/tests/test_iter110_bathy_meteo_compromised.py
  + régression iter105/108). Front e2e navigateur : water card, autre→focus,
  type météo visible, route manuelle rouge + modal risque + suivi OK.
- Backup frais : /app/backups/mongo_20260724_1906.tar.gz (13 Mo, intègre).

### Backlog (rappel)
- Plan marges latérales (en attente réflexion armateur) + déplacement réglage.
- Mode Débutant / Professionnel (évo).
- Niveau de détail carte au choix user ; hors-ligne device (build natif).
- Profils navigation (P3).

### Iter110b — 24/07 soir : réorganisation boutons hauteur d'eau (validé e2e)
- Hauteur d'eau au toucher ACTIVABLE/DÉSACTIVABLE (off par défaut) via
  nouveau bouton GOUTTE D'EAU (map-water-toggle) à l'emplacement de l'ancien
  refresh (colonne droite).
- Refresh déplacé : petit bouton rond à côté des coordonnées en haut à
  gauche (topRefreshBtn, même testID map-refresh-button).
- Icône bathymétrie : goutte → carte (Ionicons map/map-outline).

### Iter110c — 25/07 : fenêtre de navigation RÉDUCTIBLE (validé e2e)
- RouteNavPanel : props minimized/onToggleMin. GROS bouton « Réduire — voir
  la carte » (pleine largeur, 44px, teal) au bas du panneau complet.
- Mode réduit : bandeau compact 48px docké en bas (navMiniWrap bottom:6) :
  flèche relative, cap cible, distance WP, ETA + agrandir (chevron-up) +
  stop. Le bouton Signaler + colonne d'icônes remontent de 58px quand actif.
- Réinitialisé (plein) à chaque démarrage de suivi (startFollowForced).
- PIÈGE tooling récurrent : 2 corruptions de fin de fichier lors de
  search_replace proches de la fin (leaflet-html.ts, RouteNavPanel.tsx) —
  TOUJOURS vérifier la fin du fichier (tail) après édition près de la fin.

### Iter110d — 25/07 : recentrage au lancement du suivi (validé e2e)
- startFollowForced : recentre IMMÉDIATEMENT sur le bateau (userLocRef) avec
  zoom adapté à la distance au waypoint le plus proche (≤600m→z16,
  ≤1,5km→z15, ≤3,5km→z14, ≤8km→z13, sinon z12) + suspendFollow(false)
  (la caméra reprend le bateau même si l'auto-suivi avait été suspendu).
- Deps useCallback passées de [] à [route].

### Iter111 — 26/07 : lot bugs vidéos armateur (validé testing_agent 8/8 backend + 6/6 frontend)
- **P0 Règle des 150 % (route dangereuse)** : backend routing.py renvoie
  `low_margin{min_height_m,required_m,alert_at_m,safe_extra_m:2}` quand la
  hauteur d'eau min < 1,5 × (tirant + marge). Frontend map.tsx : modal
  « Route à faible marge de sécurité » (testIDs low-margin-safer/keep/later) —
  bouton « Route plus sûre (+2 m) » relance computeSafeRoute avec
  safety_extra_m (échec → route actuelle CONSERVÉE), « Garder cette route »
  = acceptation explicite. startFollow BLOQUÉ tant que non accepté
  (lowMarginAccepted, reset à chaque nouvelle route). Contexte du calcul
  dans lowMarginCtxRef (dest/from/info).
- **P0 Tuiles blanches au démarrage** : leaflet-html.ts `_retileMissing()`
  (3 passes 1.2s/3.5s/8s) : invalidateSize + re-fetch des SEULES tuiles
  incomplètes (cache-buster boot=). Prefetch lissé 60→100 ms/tuile, départ
  différé 1,5 s (tuiles visibles prioritaires). ⚠️ Un cycle de test avait
  fait disparaître ce bloc — re-vérifié présent + e2e 264 tuiles chargées.
- **P1 Compas de mesure** : segment par défaut ORIENTÉ géographiquement —
  axe de navigation (cap) si bateau en route (≥3 km/h), sinon plein
  NORD-SUD (A sud → B nord, 000°). Longueur ≈ ¼ du petit côté écran.
- **P1 Bannière écart de route** (remplace le toast) : carte persistante
  (deviation-card) avec « Couper l'alerte » (mute son+vibration via
  deviationMutedRef, réarmé au retour sur route), bouton Réglages
  (/profile/settings), X → pastille rouge « Écart Xm » (deviation-pill)
  ré-ouvrable. Distance rafraîchie à chaque tick GPS.
- **P1 Conflits UI** : cône Nav MASQUÉ quand mode hauteur d'eau actif
  (coneHalfAngleDeg/coneDistanceKm = null si waterTapOn ; alertes sonores
  du cône INCHANGÉES). Tap sur la fiche hauteur d'eau = désactive le mode
  (X = ferme seulement la fiche). Menu appui long : garde 700 ms
  anti-fermeture fantôme (longPressOpenedAtRef).
- **P2 Vigie/radar scintillement** : anneaux radar dans un PANE SVG dédié
  (smRadarPane z350 + renderer séparé) → plus d'interférence avec le
  redraw du compas de mesure/routes dans le SVG overlay partagé.
- **P2 Recentrer** : appui LONG = suspendFollow(true) + toast (auto-
  recentrage désactivé) ; tap normal = réactivation + recentrage (inchangé).
- Tests backend : /app/backend/tests/test_iter111_low_margin_rule.py (8).
- Décision armateur : mouillages cliquables via ingestion VECTORIELLE
  Overpass/OSM (à faire) ; cartes offline = feature séparée plus tard.

### Iter112 — 26/07 après-midi : lot retours armateur (testing_agent backend 13/13 + frontend, e2e complémentaires main agent)
- **P0 MOUILLAGES (routage)** : scripts/ingest_moorings.py (Overpass
  seamark:type=mooring, 1490 bouées façade dont 554 Golfe) →
  data/bathy/moorings.json. core/seamarks.py : disque interdit R=45 m par
  bouée dans rasterize_blocked, EXEMPTION 400 m autour du départ/arrivée
  (strict_exempt), contextvar MOORINGS_OPEN. routers/routing.py : si tous
  les paliers échouent → retry mouillages OUVERTS + warning « TRAVERSE une
  zone de mouillage » + through_moorings:true. Bouées cliquables via
  /api/bathy/seamarks (kind=mooring, libellé « Bouée de mouillage »).
  Testé : contournement 234 m ; destination dans le champ → autorisé.
- **P0 Hauteur d'eau AU POINT** : pastille leaflet .sm-tag (💧 + texte) au
  point cliqué via window.__setWaterPoint (prop waterPoint MarineMap),
  fermeture auto 5 s (4 s si erreur), retry auto 1× sur échec API + message
  « indisponible » (bug « mouline puis disparaît »), tap pastille = mode off
  (event water_close). Plus de carte en bas. ⚠️ CE BLOC A ÉTÉ PERDU 2× dans
  leaflet-html.ts après des cycles de test — TOUJOURS re-vérifier par grep.
- **P0 Comparatif route plus sûre** : bouton « Comparer avec une route plus
  sûre (+2 m) » → calcul en preview (computeSafeRoute(..., preview)) SANS
  remplacer, modal tableau Distance/Durée (vitesse croisière)/Fond min,
  boutons safer-adopt / safer-keep-current (acceptation explicite).
- **P1 RouteCard graphe** : label « Départ ▸ » + drapeau 🏁 (sens), bande
  ROUGE = zone sous le seuil 150 % (low_margin, marée incluse), tap sur la
  bande (route-chart-danger) → flyTo centré/zoomé sur la section (fiche → min).
- **P1 Édition de route par waypoints** : appui long SUR le tracé (< 80 m)
  → mode édition (editPoints, pins draggables __setDraftRoute), appui long
  près du tracé provisoire = waypoint en plus (< 150 m), tap À CÔTÉ ou
  bouton Valider → POST /routes/manual (revalidation), risk/compromised +
  low_margin (règle 150 % ajoutée à /routes/manual, sans bouton comparer
  car pas de recalcul auto sur tracé manuel). Barre route-edit-bar
  (Annuler/Valider). Testé e2e (login OTP requis, 401 en démo).
- **P1 Profil « Mes routes »** : section au-dessus de « Mon historique »,
  5 dernières routes (nom/km/mode/date), boutons Détails & Suivre →
  navigation vers la carte avec params saved_route_id/saved_route_action,
  bouton « Retour au profil » (map-back-profile), suivi auto via
  pendingFollowRef (gating risque/150 % conservé). Bouton « Mes routes
  enregistrées » RETIRÉ du popup Créer une route (+ modal supprimé de map.tsx).
- **P2 Suivi en incrustation douce** : RouteNavPanel plein = CHIPS
  translucides séparées (cap à suivre/actuel/vitesse/WP/arrivée + boutons
  ronds réduire/stop), plus de panneau sombre masquant le cône.
- **P2 Recentrage** : suspendFollow(true) à CHAQUE affichage de route
  (auto/manuelle/enregistrée/douteuse) — le recentrage ne reprend qu'au
  démarrage du suivi (startFollowForced) ou tap bouton recentrer.
- Reste à tester SUR APPAREIL (GPS réel) : bannière écart, chips en suivi,
  compas sur l'axe de nav en mouvement.
- Backlog inchangé : marge latérale dans « Navigation et routes », mode
  Débutant, cartes offline, aperçu comparatif → OK fait cette itération.

### Iter113 — 26/07 soir : écart minimal aux balises (retour armateur La Vilaine)
- **Fix** : core/seamarks.py — R_MARK_STANDOFF_M=60 m : disque interdit
  TOUTES DIRECTIONS autour de chaque latérale/cardinale, appliqué APRÈS le
  « couloir libre » (le cœur du chenal reste ouvert). Garde-fous : rayon ≤
  25 % de l'écartement du couple (chenaux étroits passables), sauté si
  maille > rayon, en dernier recours (MOORINGS_OPEN) et < 200 m du départ/
  arrivée. Vérifié : chenal de Vannes 61 m mini (toujours passable), Golfe
  63 m, pytest iter111 8/8.
- **DÉCOUVERTE DATA importante** : les bouées de La Vilaine (secteur
  47.86,-2.32, « No8 », « N°1 »…) N'EXISTENT PAS dans les données
  vectorielles OSM (vérifié par 3 requêtes Overpass : 0 seamark node dans
  47.80-47.92/-2.45--2.20 hors barrage d'Arzal). Elles ne sont visibles que
  dans le RASTER OpenSeaMap. → le moteur ne peut PAS les éviter tant que la
  donnée vectorielle n'existe pas. Pistes : contribution OSM, ou source
  alternative (SHOM). L'utilisateur doit en être informé.
- **Crash app signalé par l'utilisateur** : vidéo + logs NON REÇUS (seules
  2 captures jointes). Backend sain (aucun 500). À réclamer.

### Iter114→118 — 26-27/07 : marée instant T, parcs marins, mouillages surfaciques, perf numba (résumé)
- Iter115 : marée à l'INSTANT T (height_start_m), nearest_reachable validé
  pleine réso, dernier recours étagé (SIDE_RULES_OPEN), troncature adaptative
  (_trunc_cap_m). Vilaine : arrivée à ~1 km du barrage à PM.
- Iter117 : parcs de culture marine INTERDITS sans exemption (marine_farms.json,
  ~979 polygones → semis de disques), marée H+30 min (TIDE_LEAD_S=1800),
  écart balise conservé autour d'une arrivée DÉPLACÉE, arrivée jamais sur la
  vasière (préférence thalweg), retry 2× POST routes sur 429.
- Iter118 : perf routage ~32 s → ~5 s (noyau A* JIT numba `_astar_nb_core`,
  repli Python), ingest_anchorages.py (zones de mouillage surfaciques OSM →
  anchorages.json, disques R=80 m, maille ≤ 35 m, exemption 400 m dép/arr),
  bouton « Signaler » repositionné (map.tsx), texte « Recherche d'une route
  plus sûre » conditionné.

### Iter119 — 28/07 : CONTRAINTES DURES chenaux/balises + DÉCOUPLAGE MARÉE/ROUTAGE (consigne support/armateur)
Directive : « contraintes dures au lieu de pénalités douces sur les polygones
de chenal et de parcs ; découpler la marée du routage : router au pire cas ZH
d'abord, puis ajouter la fenêtre de marée. »
- **Standoff balises DUR** (core/seamarks.py) : plancher R_MARK_STANDOFF_MIN_M
  =15 m (le rayon ne descend plus à ≤ 25 % de l'écartement) et le disque n'est
  PLUS JAMAIS sauté en maille fine (bug : n°6 chenal de Vannes, couple 78 m →
  rayon 19,4 m < maille 20 m → disque sauté → route SUR la bouée). Maille
  grossière > 45 m : passes fines. standoff_circles (audit) aligné.
- **BUG QUINCONCE corrigé** (seamarks.gates) : pour les couples décalés le
  long du chenal (No7/No8), le vecteur brut du couple pointait LE LONG du
  chenal → l'« attraction de porte » pénalisait le chenal lui-même et
  laissait la vasière voisine gratuite. gates() ne garde que la composante
  PERPENDICULAIRE à l'axe (comme _mark_dir) ; couples à transverse < 60 % du
  brut = ignorés (pas des portes fiables).
- **MURS DE PORTE durs** (routing.py _nav_for) : bande mince le long de la
  ligne de chaque porte rouge/verte — l'eau PEU PROFONDE (fond < strict_depth)
  hors de la porte (|s| > 0,7×gap, jusqu'à max(2,5×gap, 450 m)) est INTERDITE
  dans le masque A* (maille ≤ 45 m, exemption 400 m dép/arr). Même contrôle
  ajouté à _corridor_safe (gates_arr) et propagé à _repair_segments,
  _straighten, _round_pts : le redressement ne recoupe plus la vasière que
  l'A* venait d'éviter. Vérifié : Golfe→Vannes à +4 m passe PAR les portes
  (35-36 m de No6/No8, 92 m d'Holavre), plus jamais à 280 m à l'est.
- **DÉCOUPLAGE MARÉE/ROUTAGE** (routers/routing.py _run_zh_tide) : route
  calculée au PIRE CAS ZH d'abord (tide=min(0, marée) — marée négative
  gardée). Marée utilisée SEULEMENT si (a) ZH échoue (chenaux découvrants →
  route annoncée dépendante de la marée, warnings historiques conservés) ou
  (b) arrivée ZH tronquée > 800 m ET la marée approche > 500 m de plus.
  Route ZH : nouveau message « Route calculée à MARÉE BASSE (zéro
  hydrographique)… Info marée : +X m ~30 min après le calcul » (substring
  « 30 min après le calcul » conservée pour les tests). result.tide_m =
  hauteur RÉELLEMENT utilisée par le routage (0 pour ZH). tide_better/
  tide_retry/tide_window inchangés. Dernier recours SAUTÉ sur la tentative
  ZH quand un repli marée existe (perf).
- **Hauteur d'eau au point** : latence bornée (asyncio.wait_for 2,5 s sur
  tide_window dans /api/bathy/depth → repli « marée indisponible ») + fix
  COURSE de requêtes côté map.tsx (waterReqRef : les réponses périmées d'un
  ancien tap n'écrasent plus le tap récent — « hyper lente, parfois rapide »).
- Tests : pytest iter93→117 + iter111/112/115/116 = 54 verts, 3 skips
  légitimes (mortes-eaux). Scripts de vérif : scripts/check_iter119.py,
  scripts/check_iter119_e2e.py.

### Iter120 — 28/07 : refonte navigation (sortie en mer 29/07) + fiche bateau + graphe marée
- **Moteur FIGÉ + BACKUP** : /app/backups/moteur_iter119_20260728 (core/, routers/,
  scripts/, tests/, JSONs balisage — les .npy restent dans data/bathy).
- **Crash croix rouge (gel 09:44:37, logs perdus)** : croix verte/rouge SUPPRIMÉES.
  « Suivre cette route » lance la navigation IMMÉDIATEMENT ; arrêt via bouton
  « Stopper la navigation » sous le tableau de bord (stopFollow durci try/catch).
  Cycle démarrer/stopper 2× validé sans gel par le testing agent.
- **Accusé de lecture** : bouton « Ok, j'ai compris » (RouteCard, sous les
  avertissements) OBLIGATOIRE — « Suivre cette route » grisé avant (routeAck,
  remis à zéro à chaque nouvelle route).
- **Navigation PLEIN ÉCRAN** : icônes refresh/vitesse/tous types/cloche masquées
  (navActive), remplacées par RouteNavPanel sur UNE ligne : CAP actuel, VITESSE
  RÉELLE live (tap = nd ⇄ km/h, clé partagée sm.speedo.unit), PROCHAIN WP,
  ARRIVÉE (ETA garde la vitesse de croisière en secours à l'arrêt). Bandeau
  réduit (navPanelMin) supprimé. Bouton « Retour au profil » masqué pendant la
  navigation.
- **CAP À SUIVRE sur la carte** : projection VERT FONCÉ (#15803D + halo blanc)
  clonée de la projection de cap, leaflet __setTargetBearing(deg), suit le
  bateau à chaque tick GPS ; tap sur la ligne → étiquette « Cap à suivre — XXX° »
  (3 s). Prop MarineMap targetBearingDeg (bearingToNextDeg).
- **Mini-graphe de marée 24 h** (RouteCard) : GET /api/tides/curve (core/tides.py
  tide_curve, pas 30 min, port le plus proche) → TideMiniGraph.tsx (SVG, courbe
  + seuil requis pointillé orange + zones PASSABLES soulignées vert ; route ZH
  → tout vert « passable à TOUTE marée »).
- **Réglages → Mon bateau DIRECT** (settings.tsx : rangée qui push /profile/boat,
  accordéon supprimé). Page boat.tsx en 2 onglets : « Réglages de sécurité »
  (tirant d'eau, marges, latérale auto/manuel, croisière, conso) et « Mon
  bateau » (BoatInfoForm.tsx : nom, photo galerie+caméra base64 via toDataUri +
  contrat permissions, type moteur/voilier, longueur, largeur, tirant d'air
  (partagé boat-settings), type moteur HB/inboard, nb moteurs 1-4, marque avec
  tête de liste imposée Mercury/Yamaha/Suzuki/Honda ou Volvo Penta/Yanmar/
  Nanni/Vetus + recherche (src/lib/engine-brands.ts), puissance par moteur).
  Persistance locale sm.boat.info (src/lib/boat-info.ts).
- Tests : backend 5/5 (tests/test_iter120_p0.py) + frontend P0/P1 tout vert
  (rapport iteration_114.json). Reste cosmétique : warnings RN-Web shadow*.

### Iter121 — 28/07 : projection de cap RÉEL (ligne rouge) rétablie (retour armateur)
Bug : la ligne ROUGE (projection de cap réel du bateau) avait disparu — (1) en
SUIVI DE ROUTE seule la ligne verte « cap à suivre » s'affichait ; (2) en mode
Navigation simple, plus aucune projection. RCA : refreshTrail() (leaflet-html.ts)
était gardé par les seuls paramètres du cône (coneHalfAngle/coneDistanceKm =
mode Navigation) → en suivi de route (navFollow) sans mode Nav, cône null → rouge
non tracée. Fix : drapeau dédié SM.headingLineOn + window.__setHeadingLine(on) ;
refreshTrail dessine la rouge (#E63946) si headingLineOn OU cône actif. Prop
MarineMap showHeadingLine={(navMode || navFollow) && !waterTapOn}. Résultat :
rouge (cap réel) + verte (#15803D cap à suivre) tracées SIMULTANÉMENT en suivi
de route, et rouge présente en Navigation simple. Validé 4/4 (iteration_115.json).

### Iter122 — 28/07 : pastilles .sm-tag toujours horizontales (retour armateur)
Bug : en mode course-up (carte tournée de -bearing), le texte de la pastille
« hauteur d'eau au toucher » (et les autres .sm-tag) tournait avec la carte →
illisible. Fix : wrapper CSS .sm-tag-anchor qui CONTRE-tourne de +bearing
(var --sm-counter, transform-origin 0 0), même mécanisme que .sm-boat-wrap/
.sm-user. Appliqué aux 4 pastilles (hauteur d'eau, cap à suivre, « reste X à
vue », « Blocage ici »). No-op en nord-en-haut. Validé (iteration_116.json) :
.sm-tag-anchor porte rotate(+bearing), .sm-tag ne garde que la translate →
texte horizontal à l'écran en course-up 45°/90°.

### Iter123 — 29/07 : correctifs post-TEST EN MER (plan segmenté validé armateur)
Choix armateur : (1) ordre du plan validé ; (2) alléger les couches selon le
zoom ; (3) « à l'arrêt de la navigation, TOUT s'arrête » ; (4) GPS dégradé =
simple avertissement « précision réduite ». Correctifs livrés :
- **Clics décalés en course-up (pastille hauteur d'eau + signalement posé à
  terre)** : le div #map étant CSS-roté, getBoundingClientRect() renvoyait la
  boîte englobante tournée → mouseEventToContainerPoint PATCHÉ (leaflet-html.ts)
  pour contre-roter le vecteur écran depuis le centre du viewport (même math
  que vpToLatLng). Corrige TOUS les taps (hauteur d'eau, appui long, cônes).
  No-op en nord-en-haut.
- **Compas de mesure « fou »** : le patch de rotation du drag n'était appliqué
  qu'au Draggable de la CARTE → déplacé sur le PROTOTYPE de L.Draggable :
  épingles A/B du compas + waypoints manuels se draguent droit en course-up.
- **Recentrage garde le zoom** : map.tsx recenter() n'impose plus le zoom 13.
- **Cône de navigation en SUIVI DE ROUTE** : coneOn = (navMode || navFollow)
  && !waterTapOn (avant : navMode seul). Radar Vigie coupé pendant le suivi.
  useConeState reçoit navMode||navFollow.
- **Ligne VERTE « cap à suivre » RETIRÉE** (doublonnait la projection rouge à
  la mer) : targetBearingDeg n'est plus passé (infra conservée si retour).
- **Taches noires zones de mouillage** : les zones de tap seamark étaient des
  disques noirs à 1 % d'opacité → en champ de mouillage dense, l'empilement
  devenait NOIR (1-(1-0.01)^300 ≈ 95 %). fillOpacity 0 STRICT (le fill SVG
  capte toujours les taps) + bouées de mouillage cliquables seulement à z ≥ 14
  (allègement par zoom).
- **Alarme d'écart : tout s'arrête** : stopFollow réinitialise routeGuardRef +
  stopRouteDeviationSound() (nouvel export alert-sound.ts) + stopAlertFeedback.
  playRouteDeviationSound recrée le player natif s'il est corrompu (retour mer
  « pas de son ») au lieu d'échouer en silence.
- **Pastille « Précision GPS réduite »** : hystérésis 35 m / 22 m sur
  p.coords.accuracy (2 watchers), pastille orange non bloquante (testID
  gps-poor-pill), styles map-styles.ts.
- **IALA cardinales (backend, moteur figé PRÉSERVÉ)** : demi-disque interdit
  CÔTÉ DANGER des cardinales de direction connue élargi 120 → 300 m
  (R_CARDINAL_WRONG_SIDE_M, core/seamarks.py) — la route ne passe plus « au
  nord d'une cardinale sud » près de la balise. Exemption < 500 m dép/arr
  (on quitte son mouillage), clearance de redressement inchangée (120 m tous
  côtés). Test iter102 fallback Arradon assoupli à une PROXIMITÉ < 100 m
  (le 1er waypoint bouge de ~27 m — attendu).
- **REPORTÉ à la séance « plan calculs de route » (vidéo Navionics annoncée)** :
  virages injustifiés (Dumet/Hen Tenn), timing de virage trop tardif autour
  des bouées, choix du côté le plus profond pour les dangers isolés, refonte
  des calculs selon hauteurs d'eau. Écart sondeur 1,8 m vs app 4,2 m :
  limite de résolution du MNT SHOM (100 m au large / 20 m côtier) — à
  expliquer à l'armateur.
- Tests : pytest iter101/102/119 + nouveau test_iter123_route_after_seamarks_300.py
  verts ; frontend e2e tout vert (iteration_117.json).

### Iter124 — 29/07 : RÉVISION MOTEUR « façon Navionics » (validée armateur : 1.a Oui, 2.b Supprimer, 3 #e034de, 4 GPS coordonnées fournies)
- **Routage 100 % ZH** : `TIDE_ROUTING_ENABLED=False` (routers/routing.py) —
  tout le code marée (hauteur départ, repli, fenêtres, « passera à partir
  de… ») est conservé mais NEUTRALISÉ, réactivable d'un flag (abo SHOM pro).
  Tests iter108/115/117/119 adaptés au pivot.
- **« Eau peu profonde » (cœur du pivot)** : quand rien ne passe au ZH
  (paliers de marge + dernier recours épuisés), `_run_shallow` retente
  compute_route avec seuil relâché (tide interne 6 m → plancher -2,5 m,
  mouillages ouverts, règles de côté levées, marge 10 m). La route est
  LIVRÉE (200) avec `shallow_route=true`, `risk=true`, `compromised_legs`
  (calculés par `shallow_legs()` extrait de manual_route, seuil = tirant +
  marge au ZH) et warning « ⚠ EAU PEU PROFONDE ». Le 422 ne reste que si
  même ce mode échoue (terre franche, hors couverture). Départ sur estran →
  route rouge au lieu de start_blocked (Vannes intra-muros → 422 inchangé).
  Cas de référence armateur : Arradon → barrage d'Arzal = 48 wp, ~20 rouges,
  2,5 s. Vieux `fallback_route` 422 quasi obsolète (test iter110 adapté).
- **Trait de route** : fushia PLEIN `#e034de` (leaflet __setRoute), liseré
  blanc conservé ; AUTO sans ronds de waypoints ; MANUELLE avec ronds fushia ;
  tronçons compromis ROUGE PLEIN #FF1744 + triangle ⚠ (.sm-danger-tri) au
  milieu de chaque tronçon ; tap trait/triangle → popup rouge « Eau peu
  profonde » (.sm-danger-pop). Suivi conditionné à risk-accept (existant).
- **Compas de mesure façon Navionics** (vidéo 00:09) : carte sombre
  translucide (.sm-ms-card2) centrée SUR le trait, toujours horizontale
  (sm-tag-anchor), 2 colonnes Distance | Relèvement, tap = bascule km/NM.
- **Pastille hauteur d'eau PRUDENTE** : /api/bathy/depth prend le MIN 3×3
  (±22 m) au lieu de la cellule seule (audit sondeur : 2,4 → 1,9 m à l'Île
  Longue). Verdict sondeur 1,8 m vs 4,2 m : (1) bug de tap course-up (corrigé
  iter123) = point échantillonné décalé vers le chenal (+4,6 m à 80 m E) ;
  (2) gradient MNT très raide au bord du banc (0,9→4,6 m en ±80 m) ; le MNT
  20 m à la position exacte donne 2,36 m ZH vs ~0,45 m sondeur → borne de
  résolution/interpolation au bord de banc, atténuée par le min 3×3.
- **Côté le plus profond près des dangers** (retour mer) : dans _solve_leg,
  la pénalité de proximité aux zones bloquées est MAJORÉE par la faible
  profondeur (shallow_bias = clip((8-depth)/8) × prox × 0,5) → contournement
  des dangers isolés par le côté profond + virages anticipés. Aucun effet en
  eau libre. Perf inchangée (Arradon→Houat 1,1 s).
- **Fluidité (réponse objective à l'armateur)** : Navionics = vecteur natif
  GPU ; SignalMar = tuiles raster + WebView Leaflet + SVG → build prod
  nettement plus réactif que la preview mais pas au niveau vecteur natif ;
  allègement par zoom déjà engagé (moorings z≥14).
- Tests : suite backend 86+ verts (iter101→124, dont nouveau
  test_iter124_routing_shallow_navionics.py) ; frontend iteration_118.json
  tout vert (trait #e034de sans dash, 0 rond en auto, 21 rouges + 21 ⚠ sur
  la Vilaine). RESTE À VALIDER PAR L'ARMATEUR : rendu compas en réel,
  virages Dumet/Hen Tenn en conditions réelles.

## Iter 125 — 31/07/2026 — ID public de route + capture support (préalable à la refonte du moteur)

L'armateur a demandé DEUX outils préparatoires avant de reprendre les règles
de calcul de route :

1. **ID public de route consultable par le support.**
   Chaque route (auto + manuelle) reçoit maintenant un identifiant lisible
   `R-YYYYMMDD-HHMMSS-XX` (timestamp UTC + 2 caractères aléatoires anti-collision)
   généré côté serveur et persisté dans la collection MongoDB `computed_routes`
   avec **TTL 30 jours**. La route stocke : params d'entrée (départ, arrivée,
   tirant, marges, marée demandée), résultat complet (waypoints, profil, warnings,
   corridor, low_margin, shallow_route, tide, end_snapped…). L'armateur peut
   copier l'ID d'un tap dans la RouteCard (chip fingerprint) et me le communiquer ;
   je consulte via `GET /api/routes/inspect/{route_id}` (endpoint réservé au
   compte SignalMar admin via `core.support_admin.is_signalmar_admin`).

2. **Popup clic carte + capture d'écran envoyée au support.**
   Quand l'icône goutte d'eau est **désactivée**, un tap sur la carte affiche
   un popup transparent façon Navionics :
   - Coordonnées DM (`47°36.300' N  02°49.200' W`).
   - Hauteur d'eau au ZH (`Fond au ZH : 2.8 m`).
   - Bouton 📸 « capturer + envoyer au support » visible **UNIQUEMENT** pour
     le compte SignalMar admin (téléphone `+33760071445`).
   - Bouton ✕ pour fermer.
   Le popup est toujours horizontal à l'écran (wrapper `.sm-tag-anchor`
   contre-rote automatiquement en mode course-up).
   La capture utilise `react-native-view-shot` sur la View native englobant
   la WebView Leaflet : tuiles + route (fuchsia) + balises + bathymétrie
   sont dans la capture. Format JPEG q=0.6 (~200-400 Ko). L'upload direct
   `POST /api/support/screenshot` stocke l'image base64 + contexte
   (route_id en cours, coordonnées du tap, hauteur ZH, user_loc, nav_mode)
   dans la collection `support_screenshots` (TTL 60 j). L'endpoint est
   également réservé au compte admin.

**Web preview** : la capture est indisponible dans l'iframe (cross-origin
tiles) → le bouton affiche un toast "Capture indisponible (essayez sur
mobile)". Fonctionne dans les builds natifs iOS/Android.

**Fichiers modifiés / créés** :
- `/app/backend/core/support_admin.py` (nouveau — helper `is_signalmar_admin`).
- `/app/backend/routers/routing.py` (route_id + `_persist_route` +
  `GET /routes/inspect/{id}`).
- `/app/backend/routers/support.py` (nouveau — upload + liste + détail + image).
- `/app/backend/server.py` (include support router + indices + TTL +
  `is_signalmar_admin` dans serialize_user).
- `/app/frontend/src/api/client.ts` (`sendMapSupportScreenshot`,
  `route_id`, `is_signalmar_admin`).
- `/app/frontend/src/components/MarineMap.tsx` (props `mapTapInfo`,
  `onMapTapClose`, `onMapTapSupport`, imperative `captureMap`).
- `/app/frontend/src/components/marine-map/leaflet-html.ts` (CSS
  `.sm-tap-card`, `window.__setMapTapInfo`).
- `/app/frontend/src/components/RouteCard.tsx` (chip route_id copiable).
- `/app/frontend/app/(tabs)/map.tsx` (branchement du popup + handler capture).

**Prochaine étape (demandée par l'armateur)** : reprise des règles de
calcul de route (« il y a de nombreux problèmes »). Ces outils permettent
maintenant à l'armateur de m'envoyer facilement un ID de route + une
capture pour chaque incohérence observée.

## Iter 126 — 01/08/2026 — Refactor multi-moteurs de routage (préalable à la refonte des règles)

L'armateur a demandé une isolation complète du moteur de routage pour pouvoir
tester des variantes sans casser l'existant. L'architecture retenue sépare
strictement :

**Algorithme** (code Python, versionné git) : `core.routing_engines.algos.signalmar_v1`.
Le fichier historique `core/routing.py` (1897 lignes) a été **déplacé
sans modification** vers `algos/signalmar_v1/core.py`. Le shim `core/routing.py`
ré-exporte les 5 symboles publics + toutes les constantes → **aucun test
existant n'a été modifié**. La classe `SignalmarV1(BaseAlgo)` fournit
`compute_auto` et `compute_manual` qui délèguent au module `core`.

**Moteur** (document MongoDB `engines`) : profil nommé qui lie un algo à
d'éventuels overrides de paramètres. Seed idempotent au démarrage :
- `engine_a` (« Moteur A ») — built-in, référence, non modifiable.
- `engine_b` (« Moteur B ») — built-in, clone strict de A (parent_id = engine_a).

**Fonctionnalités livrées** :
1. **Sélection depuis le profil** — Réglages › Navigation & routes affiche
   la liste des moteurs actifs, radio-select pour choisir l'actif.
   Persistance sur `users.active_engine_id`, exposé dans `/auth/me`.
2. **CRUD moteurs (admin uniquement)** — dupliquer un moteur avec un nom
   au choix (clone profond du profil, parent_id enregistré), renommer,
   activer/désactiver, supprimer.
3. **Suppression sûre** — Option A validée par l'armateur : un moteur ne
   peut être supprimé que s'il n'a JAMAIS servi à générer une route
   enregistrée ou calculée. Les built-in (A, B) sont non-supprimables.
4. **Traçabilité totale** — Chaque route calculée (`computed_routes`)
   et chaque route enregistrée (`saved_routes`) stocke `engine_id`,
   `engine_name`, `algo_id`. Le résultat du calcul inclut aussi
   `engine: {id, name, algo, algo_version}` dans la réponse HTTP.
5. **Recalcul de routes enregistrées** — `POST /api/routes/saved/{id}/recompute`
   avec un array `engine_ids` (1-6 moteurs) → renvoie N tracés parallèles,
   chacun avec son propre `route_id` (persisté 30 j pour inspection support).
   Permet à l'armateur de comparer côte à côte les tracés produits par les
   variantes sur une route de terrain réelle.

**Endpoints ajoutés** :
- `GET  /api/routing/engines`           — liste (ouverte)
- `GET  /api/routing/algos`             — admin (debug)
- `POST /api/routing/engines/duplicate` — admin
- `PATCH /api/routing/engines/{id}`     — admin
- `DELETE /api/routing/engines/{id}`    — admin (safe delete)
- `POST /api/routing/engines/{id}/active` — admin
- `POST /api/routing/user/active-engine` — per-user
- `POST /api/routes/saved/{id}/recompute` — per-user

**Workflow de modification future d'un moteur** :
- Réglage paramétrique : je change `params` du doc Moteur (aucun impact
  code). Aujourd'hui l'algo v1 ignore encore `params` — l'ajout de tunables
  se fera au coup par coup, à mesure des demandes de modification (chaque
  param exposé côté algo devient overridable côté moteur).
- Changement algorithmique : je crée un nouveau sous-package
  `algos/signalmar_v2/` (nouvelle classe `SignalmarV2`), l'enregistre dans
  `ALGO_REGISTRY`, puis rebinde le doc du moteur cible (`{"algo":"signalmar.v2"}`).
  Les autres moteurs continuent sur `signalmar.v1` sans impact.

**Non-régression validée** :
- 622 tests pytest verts. 8 échecs pré-existants confirmés identiques
  sur la version pre-refactor via déplacement temporaire (`mv`) +
  pytest — tous liés à des features désactivées (tide) ou à des tests
  polluant la DB (démo/rate-limit), aucun lié à la logique de routage.
- Compute A vs B avec les mêmes paramètres → réponses **bit-à-bit
  identiques** (attendu tant que B n'a pas divergé de A).

**Fichiers créés/modifiés** :
- Créés : `core/routing_engines/{__init__.py, base.py, manager.py}`,
  `core/routing_engines/algos/{__init__.py, signalmar_v1/{__init__.py, core.py}}`,
  `routers/routing_engines.py`,
  `src/components/RoutingEnginePanel.tsx`.
- Modifiés : `core/routing.py` (devient shim), `routers/routing.py`
  (résolution moteur + persistance + recompute), `server.py`
  (register router + seed/index), `api/client.ts` (types + endpoints),
  `app/profile/settings.tsx` (ajout du panel), `app/(tabs)/map.tsx`
  (tag engine dans saveRoute).

**Ce qui reste ouvert** :
- La refonte des RÈGLES de calcul de route (demande initiale de l'armateur)
  peut désormais commencer : chaque modification demandée sur Moteur B
  n'affectera plus Moteur A. L'armateur va communiquer des IDs de routes
  incohérentes (fonction popup carte + capture support déjà en place),
  et pour chaque cas on décidera : ajustement paramétrique (params
  override) ou variant algorithmique (nouvel algo lié à un moteur).

---

## Itération 129 (03/08/2026) — MOTEUR C (`signalmar.v3`) : règles de navigation strictes

**Demande armateur (verbatim, 03/08)** : GELER le Moteur 2 (Moteur B) et
appliquer STRICTEMENT à un Moteur 3 les 3 règles suivantes —
1. **Balisage (priorité absolue)** : le calcul doit toujours se faire dans le
   sens conventionnel (de la mer vers la terre) ; la géométrie d'une route
   doit être identique dans les deux sens ; bouées ROUGES à bâbord (gauche),
   VERTES à tribord (droite) ; une route ne doit JAMAIS échouer en « Passage
   impossible » — les tronçons peu profonds sont simplement tracés en rouge.
2. **Profondeur** : chemin le plus court dans la zone la plus profonde ; la
   profondeur prime sur la distance quand le fond est faible.
3. **Marge latérale** : 50 m par défaut partout, réductible à 20 m pour
   respecter le balisage (priorité 1) puis la profondeur (priorité 2) ; sous
   20 m inévitables, tronçon ROUGE + avertissement.

### Ce qui a été livré

**Configuration lisible** — `backend/config/navigation_rules.yaml` : les 4
règles écrites en clair, chaque valeur surchargeable par moteur (`params`).
Servie par `GET /api/routing/rules` (lecture ouverte).

**Moteur C** — `core/routing_engines/algos/signalmar_v3/` (algo
`signalmar.v3`, seedé comme `engine_c`, built-in, actif pour TOUS les
utilisateurs) :
- `direction.py` — SENS CONVENTIONNEL. Le champ « distance au large à travers
  l'eau » est RECALCULÉ sur la grille la plus FINE couvrant les deux
  extrémités (20 m en zone pilote, décimée ×7 ≈ 155 m). **Cause racine du bug
  « Illur »** : `SeamarkIndex._shelter` est calé sur ATL 100 m décimée ×8
  (≈ 800 m/cellule) → les passes du Golfe du Morbihan sont FERMÉES à cette
  maille, le BFS n'atteint pas l'intérieur et les valeurs y sont celles,
  propagées, de l'eau la plus proche (mesuré : entrée de Port-Navalo 229,7
  contre Le Hézo 226,9 → sens conventionnel INVERSÉ). Sur la grille fine :
  Port-Navalo 245 < centre du Golfe 316 < Le Hézo 346.
- Le calcul part TOUJOURS de l'extrémité la plus au large ; le tracé est
  retourné si l'utilisateur a demandé terre → mer ⇒ **géométrie identique
  dans les deux sens** (vérifié par test).
- `side.py` — CÔTÉ DE PASSAGE. Le sens conventionnel LOCAL = le cap du tracé
  au point de passage, retourné si le tracé y descend vers le large (une
  route peut traverser plusieurs bassins : sortir de la Loire puis entrer
  dans le Golfe). Le signe vient du champ « distance au large », la direction
  du cap du tracé (haute résolution). Toute latérale du mauvais côté à moins
  de 200 m est CONTOURNÉE (validation identique à la passe 3 du moteur) ;
  l'irréparable est remonté dans `wrong_side_marks` + avertissement nominatif.
- `margins.py` — MARGE MESURÉE en pleine résolution (couronnes 20 m puis 50 m
  sur 16 directions, tous les 25 m le long de chaque tronçon) : le masque A*
  ne prouve la marge qu'à la maille de calcul (75-110 m hors zone pilote).
- Échelle de repli « jamais d'échec » : marge 50 → 20 m, puis mouillages et
  côtés assouplis + seuil de fond au plancher moteur, puis en tout dernier
  ressort une ligne droite densifiée entièrement rouge.

**Priorité profondeur** — contextvar `core/nav_rules.py::DEPTH_PRIORITY`, lue
par le noyau A* historique (`signalmar_v1/core.py`, +14 lignes). Défaut
`(0.0, 15.0)` = AUCUN surcoût ⇒ **Moteurs A et B strictement inchangés**.
Coût d'une cellule = longueur × (1 + 2,5 × manque de fond), le manque valant
0 dès 15 m de fond et 1 au seuil de navigabilité.

**App** — `leg_reasons` (motif par tronçon rouge) : le tap sur un tronçon
affiche « Zone peu profonde ou découverte » ou « Marge latérale < 20 m » au
lieu du texte générique. Fiche route : bloc ROUGE « Balisage non respecté »
(balises + côté attendu + distance), bloc « Marge latérale < 20 m », ligne
verte « Côté de passage corrigé pour : … », et rappel du sens de calcul +
marge appliquée.

### Résultats mesurés (Golfe du Morbihan, chenal d'Illur)
| Moteur | Distance | Fond mini | Côté d'Illur |
|---|---|---|---|
| A (v1) | 3 743 m | 2,06 m | **mauvais côté** |
| B (v2) | 3 743 m | 2,06 m | **mauvais côté** |
| C (v3) | 3 874 m | 1,93 m | **corrigé** (`side_fixed: ["Illur"]`) |

Route longue Loire → Golfe (93 km) avec le Moteur C : 0 balise du mauvais
côté, « Fernais 25 » corrigé, plus aucun passage à ~1 m d'une bouée.

### Refactor livré dans la même itération
`frontend/src/components/marine-map/leaflet-html.ts` (2 736 lignes, un seul
template literal) découpé en `styles.ts` + `js/{bootstrap, tiles, bathy,
route, seamarks, measure, water-tap, prefetch, markers, geo, sm-api,
events}.ts`. Déplacement PUR : le HTML produit est **identique octet pour
octet** (vérifié par `scripts/verify_leaflet_split.cjs`, 141 040 caractères
dans les deux configurations de viseur).

### Tests
- `backend/tests/test_iter129_engine_c_rules.py` — 11 tests verts (règles
  publiées, seed du moteur, géométrie identique dans les deux sens, sens
  mer → terre, aucun mauvais côté, marge mesurée par tronçon, jamais
  d'échec, motif de chaque tronçon rouge, non-régression A/B + déterminisme).
- `test_iter127_routes_async.py::test_engine_a_fails_on_fragile_start`
  corrigé : il attendait un 422 alors que le Moteur A replie correctement en
  200 avec route rouge (attente erronée depuis l'origine) → renommé
  `test_engine_a_falls_back_to_shallow_route_on_fragile_start`.
- Suite complète : 661 verts / 9 échecs PRÉ-EXISTANTS (confirmés identiques
  après `git stash` des modifications : marée Open-Meteo, seeds de démo,
  rate-limit d'environnement) — aucun lié au routage.

### Reste ouvert
- Écart de profondeur Golfe du Morbihan (1,8 m vs 4,2 m relevés en mer).
- Sécurité : OTP mocké + mot de passe admin fixe.
- Édition des `params` du Moteur C depuis l'UI admin (aujourd'hui : YAML +
  override en base).

---

## Itération 130 (03/08/2026) — MOTEUR C : deux anomalies de balisage signalées par l'armateur

**Retour armateur (captures d'écran)** : « Le moteur C est pas mal du tout, il a
respecté presque toutes les balises y compris La Jument (pourtant isolée sans
voisine bâbord). Par contre il a foiré la balise Ilur. La 2e capture montre un
non-respect de la cardinale sud Drenec. C'est grave. »

### Anomalie 1 — « Illur » toujours du mauvais côté

Trois causes cumulées, toutes corrigées :

1. **Insertion du point de contournement dans un tronçon de 4,5 km.** Le
   contournement était inséré entre deux waypoints de l'A*, très espacés en eau
   franche. Le tronçon entier était donc dérouté et le contrôle de couloir le
   rejetait (mesuré : 20 candidats sur 25 rejetés par `seg_ok`). → Remplacé par
   un **PONTAGE LOCAL** (`side.py::_bridge`) : seule la portion à ±150 m de la
   balise est remplacée, par un triplet entrée / contournement / sortie
   interpolé sur le tracé d'origine.
2. **Reconstruction sautée.** `_apply_side_rules` ne reconstruisait le résultat
   que si `len(new_pts) != len(pts)`. Or le pontage retire 2 waypoints et en
   ajoute 3 : la longueur peut être identique. Le tracé restait donc INCHANGÉ
   alors que `side_fixed: ["Illur"]` était annoncé — exactement ce que
   l'armateur voyait. → Comparaison sur le CONTENU (`new_pts != pts`).
3. **Exemption non propagée.** Le veto « aucune violation nouvelle » auditait
   les voisines SANS l'exemption départ/arrivée, ce qui rejetait tout
   contournement dès qu'une balise proche d'une extrémité était non conforme.

### Anomalie 2 — cardinale sud « Drenec » non respectée

**Le Moteur C ne gérait QUE les latérales rouge/verte** : les 545 cardinales de
l'index étaient ignorées par la règle de côté, et `_Ctx.seg_ok` (héritée de la
passe 3 du moteur) ne contrôle ni les cardinales ni le côté des autres
latérales — un contournement pouvait donc en violer une autre.

Livré :
- **Règle unifiée** : on calcule `u`, le vecteur du côté où le TRACÉ doit
  passer, vu depuis la balise ; conforme si `(P − M) · u > 0`. Latérale rouge →
  `u = tribord(D)`, verte → `u = bâbord(D)`, cardinale → direction désignée
  (Sud → on passe au sud).
- **Veto anti-régression** : tout candidat de contournement est réaudité contre
  TOUTES les balises du voisinage ; aucune violation nouvelle n'est acceptée
  (corriger « Illur » ne doit pas casser « Drenec »).
- **Portée réelle du haut-fond** (`_cardinal_reach_m`) au lieu d'un demi-disque
  forfaitaire de 300 m, qui produisait deux erreurs OPPOSÉES :
  * chenal d'Arradon — 12 à 14 m de fond dès 100 m au sud de la cardinale nord
    (le danger ne fait que ~30 m) → interdiction abusive qui empêchait de
    corriger « Truie d'Arradon » ;
  * « Drenec » — 8 à 9 m jusqu'à 150 m au nord puis 0,8 m vers 300 m → un test
    « eau peu profonde entre la balise et le tracé » laissait passer un
    franchissement à 80 m.
  Mesure retenue : distance de la PREMIÈRE eau peu profonde le long de la
  direction de danger (bande ±25 m) ; l'interdiction couvre cette distance
  + 80 m, minimum 100 m. Drenec → 160 + 80 = 240 m ; Arradon → 20 + 80 = 100 m.
- **Fausse alerte des paires serrées** : une latérale APPAIRÉE n'impose son côté
  que si le tracé emprunte la porte (rayon plafonné à 0,8 × l'écartement de la
  paire). La paire du chenal d'Arradon est écartée de 65 m : une route passant à
  106 m n'y est pas.
- **Candidats « milieu de porte »** pour les balises appairées : le bon point de
  passage est le milieu de la porte, pas un écart arbitraire du bon côté (qui
  tombait sur la vasière voisine) — c'est ce qui débloque « Truie d'Arradon ».
- **Cardinale au départ/à l'arrivée** : si l'extrémité demandée est DANS le
  secteur dangereux, aucun itinéraire ne peut respecter la règle. On n'invente
  pas de détour : champ `endpoint_cardinals` + avertissement « sortez du secteur
  à vue » (bloc dédié dans la fiche route).
- **Retournement** : l'avertissement « arrivée déplacée » est réécrit en
  « départ déplacé » quand le calcul a été retourné (sinon l'app annonçait le
  déplacement de la mauvaise extrémité).

### Vérification
`scripts/diag_v3_sweep_morbihan.py` — 20 itinéraires couvrant les chenaux du
Golfe (Illur, Drenec, Creizic, La Jument, Grand Mouton, Arradon, Noyalo) :
**17 violations avant → 0 après**, dans les deux sens de parcours.

Tests : `test_iter130_engine_c_marks.py` 17/17 (règle des cardinales, portée du
haut-fond, paires serrées, balisage de bout en bout sur 6 itinéraires,
réversibilité après contournement, non-régression A/B). Suite complète :
701 verts / 9 échecs pré-existants (marée Open-Meteo, seeds de démo,
rate-limit d'environnement).

**Note d'exploitation** : le compte armateur est passé sur le Moteur C. Cinq
fichiers de tests hérités qui verrouillent le comportement HISTORIQUE
(`iter93`, `iter95`, `iter102`, `iter104`, `iter105`) épinglent désormais
`engine_id: "engine_a"` explicitement — sans quoi ils testaient le Moteur C et
échouaient sur des différences VOULUES (jamais d'échec, marge propre 50/20 m).

---

## Itération 131-132 (03/08/2026) — TRANSMISSION SUPPORT : les 3 canaux fiabilisés

**Demande armateur (verbatim)** : « J'ai besoin que tu répares la fonction qui
t'envoie automatiquement une capture d'écran avec les coordonnées précises.
Hier je t'ai envoyé les captures avec cet outil et tu n'as rien reçu. L'envoi
d'enregistrement d'écran, de captures d'écran, et cet outil doivent tous les 3
être parfaitement fonctionnels. »

**Constat en base** : dernière capture réellement enregistrée = 03/08 à 12h28
(`S-20260803-122825-W6P`), AUCUNE ensuite. Logs terrain :
`support screenshot failed {"status":429}`.

### Causes et correctifs
1. **POST unique de ~400 Ko de base64** → throttlé par l'ingress. La capture
   carte emprunte désormais le chemin CHUNKÉ (`/support/upload/init` + `/chunk`,
   morceaux de 96 Ko binaires ≈ 128 Ko en base64) puis un nouvel endpoint
   `POST /api/support/screenshot/commit` qui assemble et rattache coordonnées +
   contexte.
2. **Morceaux de la galerie/vidéo à 512 Ko** (≈ 683 Ko en base64) → réduits à
   96 Ko ; ré-essai porté de 1 à 3 tentatives avec attente croissante
   (700 / 1800 / 4000 ms).
3. **Sessions d'upload en MÉMOIRE** → un redémarrage backend renvoyait
   « Session d'upload inconnue » et l'envoi était perdu. Elles sont persistées
   (`support_upload_sessions`) et la liste des morceaux reçus est reconstituée
   depuis le disque. Vérifié : backend redémarré entre le morceau 0 et le 1,
   image relue identique à l'octet.
4. **Capture allégée** : 1080 px / qualité 0,55 (≈ 120-220 Ko au lieu de
   300-400 Ko).
5. **NAVIGATEUR** : `react-native-view-shot` ne peut pas photographier l'iframe
   Leaflet (canvas teinté par les tuiles tierces) — l'outil affichait « Capture
   indisponible » et n'envoyait RIEN. Il envoie désormais le CONTEXTE seul
   (coordonnées, tracé COMPLET, `engine_rules`, `side_fixed`,
   `wrong_side_marks`, `endpoint_cardinals`, `compromised_legs`,
   `leg_reasons`), ce qui suffit à rejouer le calcul côté serveur. `image_b64`
   devient optionnel, champ `has_image`.
6. **« Vérifier la réception »** (nouveau) : `GET /api/support/inbox` + bouton
   dans l'écran Diagnostic (`testID="diag-check-inbox"`, résultat
   `testID="diag-inbox-result"`). L'armateur voit ce que le serveur a REÇU
   (captures, fichiers, bundles de logs) avec horodatage.
7. **Progression affichée** pendant l'envoi de la capture (0 → 100 %).

### Tests
- `test_iter131_support_transport.py` 8/8 et `test_iter128_support_screenshot.py`
  15/15.
- `test_iter132_support_extra.py` 11/11 (agent de test) : multi-tailles
  60 Ko / 250 Ko / 1,5 Mo identiques à l'octet, 413 au-delà de 4 Mo, 403
  non-admin sur `/commit`, `/inbox`, `/screenshot`, `/screenshots`,
  non-régression du chemin single-shot, et **durabilité après redémarrage du
  backend en pleine session**.
- e2e web : `/diagnostic` affiche bien le résumé de réception ; `/map` charge
  sans erreur ; repli « contexte seul » vérifié de bout en bout.

## Itération 133 — 10/08/2026 : Sens conventionnel des latérales ISOLÉES (MOTEUR D)

### Consigne armateur
- Priorité absolue : appliquer STRICTEMENT le sens conventionnel au routage.
  Les moteurs ne passaient jamais du bon côté d'une latérale SEULE (une rouge
  ou une verte isolée).
- **Moteur B PROTÉGÉ et FIGÉ** (base de travail). Ne toucher qu'au Moteur D
  (créé par l'armateur en base le 10.08 : « Moteur D base B 10.08.26 »).

### Analyse (répondue à l'armateur, validée)
- Le sens conventionnel n'est pas calculable « sans faille » avec la bathy
  gratuite seule (convention réglementaire, encodée officiellement dans les
  ENC S-57 payantes du SHOM via M_NSYS/ORIENT).
- MAIS le côté de passage d'une latérale est INVARIANT au sens de parcours
  (« verte à tribord en entrant » = « verte à bâbord en sortant » = même côté
  absolu) → le problème se réduit à : de quel côté GÉOGRAPHIQUE de la bouée
  est l'eau navigable ? Déterminable par l'asymétrie bathymétrique.

### Implémentation
- `core/seamarks.py` :
  - `navigable_side(m)` : côté navigable d'une latérale isolée par asymétrie
    bathymétrique (axe du chenal → 2 côtés perpendiculaires, sinon 12 azimuts ;
    grille la plus fine ; gardes : écart ≥ 1,5 m ET côté danger < 6 m de score).
  - `mark_dir_confident(m)` : D fiable seulement (couple → override manuel
    `data/bathy/side_overrides.json` → bathy). `_pair_dir` extrait de
    `_mark_dir` (refactor neutre).
  - contextvar `ISOLATED_SIDE_BATHY` (défaut False) : armé UNIQUEMENT par
    l'algo v4. Caches séparés (`_dir_v4`, `_wrong_depth_v4`) → A/B/C
    STRICTEMENT inchangés (verrouillé par test).
  - rasterize : sous le mode D, une isolée confiante reçoit un demi-disque
    interdit PLEIN de 200 m côté danger (sans filtre de profondeur — la
    « langue » d'eau profonde entre la bouée et le danger n'est pas un
    passage ; mesuré : Illur à 79 m au sud). Couples : filtre conservé.
- `core/routing_engines/algos/signalmar_v4/` : **SignalmarV4 (Moteur D)** =
  SignalmarV2 à l'identique + mode ISOLATED_SIDE_BATHY + audit nominatif
  `wrong_side_marks`/avertissements (auto + manuel, jamais bloquant).
- `engine_d` (Mongo) rebranché de `signalmar.v2` → `signalmar.v4`.
- Moteur C : side.py avait été modifié puis ANNULÉ (git checkout) suite à la
  consigne « ne toucher qu'au Moteur D ».
- `RATE_LIMIT_BYPASS_TOKEN` ajouté à backend/.env (les tests QA en avaient
  besoin ; absent depuis l'import du repo).

### Validation (cas de référence : verte isolée « Illur », Golfe du Morbihan)
- Danger 1-2 m au SUD, chenal 11-13 m au NORD → `navigable_side` = NORD ✓.
- Moteur D : Port-Navalo ↔ Ilur E passe au NORD dans les 2 sens ✓ (B figé
  passe toujours au sud à 86 m — comportement historique conservé).
- 222/524 latérales isolées obtiennent un côté confiant ; les ambiguës (eau
  profonde des 2 côtés, ex. NE Teignouse) gardent le repli historique.
- Tests : test_iter133 8/8 ; régressions iter126 (B), iter129/iter130 (C) OK.
- Échecs préexistants NON liés : test_iter104 endpoint (user admin épinglé
  absent de la base), OTP throttle sur runs répétés.

## Itération 133 b — 10/08/2026 : bug « grosses anomalies » route Moteur D (Vilaine)

### Bug utilisateur + question
Route Moteur D Golfe → Vilaine avec balises du mauvais côté. L'armateur
soupçonnait « une fonction qui impose le respect des données de fond en
prenant le dessus sur le balisage ». Confirmé — DEUX mécanismes :
1. `_run_shallow` / `_last_resort` (routers/routing.py) : quand rien ne passe
   au ZH, relance avec SIDE_RULES_OPEN=True → rasterize levait TOUTES les
   zones de côté latérales (No1 laissée à 9,8 m du mauvais côté).
2. Passe 3 du cœur (`_straighten`/`_repair_segments` via `_corridor_safe`) :
   ne contrôle que fond + portes + cercles d'écart 60 m → retendait le tracé
   du mauvais côté (Illur recoupée à 91 m au sud en marge AUTO 10 m).

### Correctifs (Moteur D uniquement, sous ISOLATED_SIDE_BATHY)
- seamarks.rasterize_blocked : les latérales à direction FIABLE ne sont
  JAMAIS levées par SIDE_RULES_OPEN (les ambiguës restent levées — raison
  d'être historique du mode).
- seamarks.clearance_points : le demi-disque danger (200 m) des isolées
  fiables est couvert par un semis de disques d'écart (3 anneaux × 5 azimuts,
  r 45 m) → la passe 3 ne recoupe plus le mauvais côté. Aucun changement de
  signature dans le cœur gelé.
- backend/.env : ligne fusionnée SMS_PROVIDER/RATE_LIMIT_BYPASS_TOKEN séparée.

### Vérifié (testing agent, /app/test_reports/iteration_2.json)
- Illur marge AUTO : NORD dans les 2 sens (81-128 m), wrong_side vide.
- Vilaine eau peu profonde : 200, shallow_route=true, wrong_side vide.
- Moteur B figé : inchangé (pas d'audit, comportement historique).
- Suites 19/19 (iter133 + intégration testing agent) + régressions 35/35.

## Itération 135 — 11/08/2026 soir : retours armateur sur le MOTEUR E (captures)

### Bugs remontés (route Port-Navalo → Crouesty, moteur E)
1. « Grand Mouton pas respectée » : verte isolée frôlée à 72 m côté EST alors
   que le chenal profond (24 m) est à l'OUEST.
2. « Balise bâbord No2 pas respectée » : passage à 127 m du mauvais côté.
3. « Embardée à l'entrée du port » : dents de scie ±40 m sur le tronçon final.
4. (Découvert en régression) : Logoden recoupée à 71 m au NORD (chenal de
   Vannes) — la réparation gardait l'original fautif.

### Corrections (universelles, mode E / SIDE_ABSOLUTE uniquement, moteurs A-D figés)
- `seamarks.navigable_side` + `_far_channel_side` : repli CHAMP LOINTAIN pour
  les isolées posées SUR leur danger (échantillons 30-60 m noyés par la roche) :
  s'il y a un danger < 5 m à ≤ 60 m ET qu'un côté à 100-200 m (écrêtage 20 m)
  domine son opposé de ≥ 4 m → côté chenal confiant. Cache séparé `_navside_v5`.
- `seamarks.rasterize_blocked` : le plafond de densité d'un COUPLE ne
  s'applique plus au rayon 0,8 × écartement (le demi-disque d'un vrai couple
  réciproque pointe vers l'extérieur du chenal, il ne peut pas le sceller) ;
  la densité (mesurée HORS partenaire via `_nearest_other_lateral_m`) ne
  plafonne plus que l'extension peu-profonde. Exemption départ/arrivée réduite
  de 500 m à 200 m (alignée sur l'audit) — corrige « 8 » recoupée à marée haute.
- `seamarks.clearance_points` : semis de côté des couples aligné (0,8 × gap
  sans plafond densité). `standoff_circles` : écart recommandé ADAPTATIF à la
  densité en mode E (0,35 × voisine, plancher 25 m) → plus d'avertissement
  « 46 m / recommandé 60 m » dans un chenal de port.
- `signalmar_v1/core._repair_segments` (gated SIDE_ABSOLUTE) : nouvelle
  pénalité `_wrong_side_penalty_m` (mêmes règles que l'audit v4) — quand aucun
  candidat n'est parfait, on retient celui qui RÉDUIT le mauvais côté sans
  passer sous le seuil de profondeur (départage par `_clearance_worst_ratio`).
  → Logoden passée au SUD.
- `signalmar_v5._buoyed_channel_chain` : lissage — dans une fenêtre de 50 m le
  long de l'axe, seule la balise la plus proche de l'axe produit un waypoint
  → plus d'embardée. Version moteur E : 5.1.0.

### Vérifié
- Route armateur (marées 0 / 2,5 / 5 m) : wrong_side vide, Grand Mouton passée
  à l'OUEST (94-166 m), No2 > 155 m, tronçon final lisse. E2E API
  /api/routes/compute engine_e : 1 seul warning légitime (fin découvrante).
- Tests : test_iter135_retours_moteur_e.py 5/5 ; iter134 5/5 ; iter133 (D)
  10/10 + 8/8 ; iter126 (B), iter129/130 (C), iter124 : OK.
- Base forkée : user de test `user_0b6070a69154` re-seedé (les tests
  d'intégration HTTP en dépendent).

## Itération 136 — 13/08/2026 : MOTEUR F (signalmar.v6) + gel du Moteur E
### Consignes armateur
- « Le Moteur E est le meilleur. Copie-le pour créer le Moteur F, verrouille
  le Moteur E » ; priorité aux routes : balises du chenal de La Trinité non
  respectées à l'arrivée, « Truie d'Arradon » non respectée au départ
  d'Arradon (avec avertissement affiché), trajectoire en Z + N°12 (capture
  11/08). Route de référence : R-20260813-144317-MX (engine_e, marge 30 m,
  tirant+marge 1,5 m, marée 0) — retrouvée dans la base et REJOUÉE en local.
### Causes racines (mesurées, scripts/diag_trinite_truie.py)
1. Truie d'Arradon (couple avec « Le Druic », gap 344 m) recoupée à 165 m du
   mauvais côté : le masque fin bloque bien (vérifié), mais le tronçon vient
   d'une passe grossière (côté non rasterisé si maille > 35 m) jamais
   re-raffinée là, et le semis de cercles de la passe 3 a des trous (raté
   46 m). L'audit voyait (165 < 200 m), rien ne réparait.
2. La Trinité hors zone pilote (ATL100, maille 75-110 m) : côté jamais
   rasterisé ; la complétion v5 (extension A* marée +6 m) coupait la vasière
   (N°4 à 0,7 m — sur le tronçon d'approche de l'ARRIVÉE RELOGÉE de la route
   principale —, N°8 à 129 m du mauvais côté) ; reliquat d'arrivée lu depuis
   end_snapped au lieu d'être MESURÉ → arrivée manquée de 98 m sans flag.
### Correctifs (signalmar.v6 UNIQUEMENT, contextvar SIDE_ABSOLUTE_V6 ; E figé)
- `algos/signalmar_v6/sidefix.py` : post-correction géométrique du tracé
  FINAL (indép. de la maille, jamais bloquante) — (1) mauvais côtés (mêmes
  critères que l'audit v4) réparés par RE-CALCUL LOCAL pleine résolution
  (v1.compute_route sur le tronçon fautif, masques armés) sinon insertion
  d'un point du bon côté (milieu de porte si couple) ; (2) frôlements
  écartés (validation DEUX SEUILS : normal, ou marée −2,5 m si le tronçon
  d'origine était déjà rouge) ; (3) LISSAGE des épingles > 100° (le « Z ») ;
  garde-fou fond jamais dégradé, re-audit + recalcul rouges/risk/couloirs.
- `algos/signalmar_v6/__init__.py` : complétion d'arrivée v6 — extension A*
  REJETÉE si elle enfreint la discipline du chenal (latérale fiable mauvais
  côté ≤ 250 m ou frôlement < 0,6 × écart) → suivi du chenal balisé ;
  reliquat GÉOMÉTRIQUE (bug des 98 m) ; recul d'ancre (≤ 5 crans) quand
  l'approche de l'arrivée relogée frôle une balise ou DÉPASSE l'arrivée
  (U-turn de la capture Z) ; avertissement « EN ROUGE » seulement si
  tronçons compromis réels.
- seamarks.py : contextvar SIDE_ABSOLUTE_V6 ajouté (aucun usage dans les
  chemins des moteurs A-E).
- Moteurs : engine_f seedé en Mongo (« Moteur F base E 13.08.26 », algo
  signalmar.v6, parent engine_e) ; description d'engine_e marquée « FIGÉ le
  13.08.26 ».
### Vérifié
- Route MX (F) : Truie BON côté 128 m, N°4 à 113 m (0,7 m avant), N°2/
  Grassus/N°6/N°8/N°10/Dalh/N°5/N°12 tous bon côté ≥ 29 m (N°5 exempt
  arrivée), arrivée à 0 m, aucun repli > 100°, wrong_side vide.
- Route « Z » (arrivée 47.5855/-3.0235) : 0 repli (5 avant lissage), arrivée
  exacte, wrong_side vide, N°12 ≥ 40 m.
- Moteur E FIGÉ : résultat strictement identique à la route MX stockée en
  base (waypoints au mètre) — le bug Truie y reste (preuve de gel).
- Tests : tests/test_iter136_moteur_f_trinite_truie.py 10/10 ; régressions
  iter135 (E) 5/5 + iter134 5/5 + iter133 (D)/iter129/iter126 (B) 57 verts.
  iter130 : 26 erreurs PRÉ-EXISTANTES (throttle OTP + ancien token bypass).
- E2E API : POST /api/routes/compute/async engine_f → job done, wrong_side
  vide, arrivée atteinte, chip « Moteur F base E 13.08.26 · engine_f ».

## Itération 137 — 14/08/2026 : cardinale ≠ chenal scellé + bouton signalement
### Bugs armateur (captures 14/08, moteur F)
- R-20260814-164055-B5 : détour ~1 km par le NORD au lieu du chenal court
  Truie d'Arradon ↔ Holavre/Le Druic ; R-20260814-165115-CT (11 min après,
  départ à 160 m) divergeait (« cardinale privilégiée »).
### Cause racine (mesurée)
- Cardinale NORD à 114 m de la Truie : son demi-disque danger (300 m S)
  scellait l'ENTRÉE du chenal en maille grossière 100 m (le masque fin 20 m
  était OUVERT, fonds 4-15 m ; le couloir libre du couple ré-ouvrait trop
  peu de cellules à 100 m) → la passe grossière partait au nord et les
  fenêtres fines ne revisitaient jamais le chenal.
### Correctifs
- seamarks.rasterize_blocked (gated SIDE_ABSOLUTE_V6, Moteur F UNIQUEMENT) :
  rayon « mauvais côté » d'une cardinale plafonné à 0,9 × la latérale la
  plus proche (plancher 120 m historique) — la latérale fait autorité sur
  la limite du chenal. Universel, aucune exception de terrain.
- v6._complete_truncated_end : purge des warnings de FRÔLEMENT devenus
  obsolètes après fusion/recul d'ancre + ré-audit (_mark_pass_audit) du
  tracé fusionné (warning « passe à ~1 m de N°4 » restait à tort).
- **Bouton « Signaler un balisage non respecté »** (demande armateur) :
  RouteCard → modal (balise + commentaire) → POST /api/routes/mark-report
  (snapshot auto : route_id, moteur, wrong_side_marks, warnings balisage,
  request) → collection mark_reports, report_id « BR-… » ; GET
  /api/routes/mark-reports (ses signalements, TOUS pour l'admin).
  Fichiers : routers/routing.py (2 endpoints), src/api/client.ts
  (reportMarkIssue), src/components/RouteCard.tsx (bouton + modal,
  testIDs route-mark-report-*).
### Vérifié
- B5 : 23 602 → 22 739 m, chenal court, tracé au S de la Truie (146 m) /
  au N du Druic (152 m) ; CT : 22 646 m, même corridor → convergence.
- Moteur E figé : B5 reprend le détour nord historique (gel prouvé) ; cap
  cardinal actif SEULEMENT sous SIDE_ABSOLUTE_V6 (test masque 100 m E vs F).
- Tests : test_iter137_cardinale_chenal.py 6/6 ; iter136 10/10 ;
  régressions iter126/129/133/134/135 : 60 verts.

## Itération 138 — 14/08/2026 : correctifs de l'audit QA externe (40 défauts triés)
### Décisions armateur : mot de passe oublié → PLUS TARD ; couverture Europe → PLUS TARD ; Moteur D (arrêt 1 309 m) → NE PAS TOUCHER (figé).
### Corrigé (backend)
- P0/FND-004 : Moteur F — JAMAIS de tronçon SUR TERRE : la complétion sonde
  chaque tronçon ajouté tous les ~25 m ; TERRE (fond < −3,5 m ZH ou hors
  donnée) → troncature au dernier point EN EAU + end_snapped
  {reason: arrivee_a_terre} + warning franc (fini le tracé à −13,8 m sur le
  Crouesty avec message « chenal balisé »). FND-040 : completion_failed=True
  si la complétion lève. Moteur E conservé bugué (gel).
- FND-042 : routeur /api/dev/* verrouillé par ALLOW_DEV_SWITCH (env) — posé
  en dev (.env), ABSENT en prod → 403. ⚠ CHECKLIST DÉPLOIEMENT : ne pas
  copier cette variable en production.
- FND-001/002/038 : champ frozen posé sur engine_a..e (ensure_seed
  idempotent) ; rename/delete/deactivate REFUSÉS sur figés ; noms uniques ;
  list_engines expose frozen + algo_version (FND-026).
- FND-003/004 : engine_id explicite inconnu/désactivé → 404 AVANT création
  du job (compute, compute/async, manual, recompute/async) ; préférence
  perso retombe sur le défaut ; ?include_inactive=true (admin) sur
  GET /routing/engines ; delete_engine désindexe active_engine_id des users
  (FND-032).
- FND-012 : GET /routes/job/{id} ne détruit plus le job (relisible 15 min,
  GC existant).
- FND-028 : OTP faux 401→400 ; inscription en double 400→409. FND-024 :
  notification inconnue → 404. FND-015 : bbox inversée → 422. FND-014 :
  recompute/async d'une route inexistante → 404. FND-017 : anti double-tap
  signalement (même auteur/type, <90 s, <~120 m → renvoie l'existant,
  duplicate=true). FND-031 : diagnostics rattachés au compte connecté.
  FND-022 : points-history limit max 50→200.
### Corrigé (frontend)
- FND-009 : login EMAIL + MOT DE PASSE (login.tsx, testIDs login-mode-email,
  login-email, login-password, login-email-submit ; AuthContext.loginWithEmail,
  api.loginEmail).
- FND-011 : fetchReports géofiltre TOUJOURS (GPS sinon CENTRE COURANT de la
  carte via mapCenterRef, sinon DEFAULT_CENTER) — plus jamais toute la base.
- FND-013 : astuce visible sur la RouteCard (« appui long sur le tracé pour
  déplacer le waypoint le plus proche »).
- FND-037 : ReportSharePreview rend une iframe srcDoc sur web (plus de
  « React Native WebView does not support this platform »).
### Non traité (assumé)
- FND-016/029 (données prod), FND-030 (démo 0 balise — à investiguer),
  FND-033 (route manuelle, moteurs figés), FND-005/(P1-6 Moteur D figé),
  P1-7 (complétion du DÉPART — backlog), FND-034/035/036 (low),
  mot de passe oublié + Europe (décision armateur : plus tard).
### Tests : tests/test_iter138_audit_qa.py (4) + iter136/137/135/133 = 34 verts.

## Itération 139 (26/08/2026) — Balises de chenaux respectées (Moteur F) + zones rouges précises cliquables
### Bug armateur (25/08) : balises non imposées à Lorient (« La Petite Jument »,
### N° 2/3/4/6/7, « Banc du Turc », « Écrevisse »), au Croisic (« Les Rouzins »)
### et au Golfe (« Kerpenhir »). 5 causes racines corrigées (gated v6 uniquement) :
1. seamarks.mark_dir_confident : le cache `_dir_conf_v5` court-circuitait le
   bloc V6 (un None v5 empêchait l'héritage de direction) → le cache v5 n'est
   plus retourné en mode V6, seulement réutilisé comme base.
2. sidefix._side_insert/_graze_insert : la fenêtre de validation englobait des
   segments INCHANGÉS déjà « rouges » (arrivée découvrante) → toutes les
   réparations étaient rejetées au fond. Un segment identique au tracé courant
   n'est plus re-validé (cur_segs).
3. enforce_mark_sides : les phases côtés/frôlements sont rejouées une 2e passe
   (réparations interdépendantes : écarter N° 3 débloque Banc du Turc).
4. Faux couple « N° 4 »–« N° 3 » (direction SW absurde) : si la direction du
   couple est OPPOSÉE au consensus des latérales fiables voisines et que la
   bathy est muette, le consensus prime (_dir_v6_inferred).
5. « Écrevisse » : sur un LONG bord (> 900 m), variante « épinglée » (± 300 m
   autour de la balise, le reste du bord garde sa ligne) + une infraction
   PRÉEXISTANTE sur le tracé courant (épave frôlée à 38 m) ne bloque plus une
   réparation (_seg_marks_ok(ref=pts)).
### Résultat : route Lorient (entrée du port) = 0 balise du mauvais côté (6 avant).
### Feature carte (demande armateur) : zones ROUGES PRÉCISES
- route.ts (__setRoute) : le rouge #FF1744 est peint sur les échantillons du
  depth_profile SOUS le seuil (interpolation aux bords), plus jamais le tronçon
  waypoint-à-waypoint entier. Fallback tronçon entier si raison low_margin ou
  profil muet (aucun avertissement perdu). Triangle ⚠ par zone.
- Tap sur une zone rouge → postMsg route_tap + danger{min_depth_m, threshold_m,
  reason} → le menu « Route sûre » s'ouvre AVEC un bandeau rouge
  (testID route-menu-danger) « Hauteur d'eau insuffisante ici : fond mini ~X m
  pour un besoin de Y m » ET toutes les options habituelles.
### Tests : tests/test_iter139_directions_chenaux.py (6) + e2e
### tests/test_iter139_e2e_lorient.py (3) ; régressions iter136/137/138 = 26 verts.
### Baseline git stash : les échecs e2e iter101/103/104 + OTP 429 sont
### PRÉEXISTANTS à l'environnement du fork (identiques avant/après correctifs).

## Itération 140 (27/08/2026) — Refactor map.tsx (backlog approuvé iter138)
- map.tsx : 4 774 → 4 125 lignes. Déplacement PUR (zéro changement visible) :
  - src/screens/map/map-constants.ts : libellés balises FR, DEFAULT_CENTER,
    DISPLAY_RADIUS_KM, seuils bascule Vigie/Nav, bornes du cône.
  - src/screens/map/route-geometry.ts : nearestSegOnRoute, nearestWpIdx.
  - src/screens/map/modals/ : 12 composants typés — UnitPicker, BathyOpacity,
    Anchor, LongPressMenu, AlertSettings, LowMargin, SaferPreview,
    RiskConfirm, RouteMenu (avec bandeau danger 26/08), RouteChoice,
    SaveRouteName, SeamarkInfo. Tous les testIDs conservés.
- L'état et les handlers restent dans MapScreen (props explicites).
- Restent dans map.tsx (extraction future si besoin) : modal recherche,
  feuille de filtres, modal cône, barres pick/manual/edit.
- Non-régression : iteration_7.json 10/10 verts (simulation MessageEvent).

## Itération 141 (27/08/2026) — Perf : calcul de route < 10 s (demande armateur)
Cause de la lenteur (~30 s Lorient → Golfe) : cascade de CALCULS COMPLETS
séquentiels (ZH exhaustif en échec + marée + « eau peu profonde ») × un A*
en Python pur (numba absent de l'env) × 252 rasterisations par calcul.
1. numba installé (requirements.txt) → le cœur A* JIT `_astar_nb`
   (signalmar_v1/core.py, prévu par conception 27/07/2026) est actif :
   même algorithme, 30-80× plus rapide, GIL libéré (nogil).
2. seamarks.RASTER_CACHE (contextvar, défaut None = A-E inchangés) : cache
   de `rasterize_blocked` par fenêtre pour la durée d'UN calcul v6 — armé
   dans SignalmarV6.compute_auto.
3. routers/routing.py : `_run_zh_tide` lance ZH et MARÉE en PARALLÈLE
   (asyncio.gather) ; chaque branche suit sa marge dans une `margin_box`
   (le nonlocal used_margin n'est plus écrit en concurrence). Sémantique du
   28/07 INCHANGÉE (ZH préféré ; marée si échec ou arrivée > 800 m).
Mesures (API, engine_f) : Lorient→Golfe 16,2 s → 8,1-8,3 s ; Lorient→La
Trinité 2,2 s → 1,3-1,6 s ; warm-up post-restart ~1,5 s.
Non-régression : 26/26 balisage (iter136-139) + 40/40 moteurs gelés
(iter124/129/130/133) + test perf dédié tests/test_iter140_perf_route_10s.py.

## Tests ITER143 (agent de test, iteration_10.json) : TOUT VERT
- Backend 15/15 (8 iter143 + 3 review extra + perf 4+1 xfail), frontend :
  filtres/cône/barres extraits OK, aucune erreur console, moteurs A-G intacts.
- Cosmétique non bloquant : warnings RN Web shadow*/pointerEvents (backlog).

## ✅ ITER144 (27/08) — nettoyage FAUSSES SURFACES lidar (GO armateur, données uniquement)
- Bug « Passage impossible » à la Jument (tirant 1.5, marée 0) : cause = lidar
  « fausse surface » (cellules natives 0.4-1.1 m dans des passes à 10-20 m,
  confirmées ATL100) + lacunes bloquées par la protection assèche ≤2 cellules.
- Fix ingestion (scripts/ingest_litto3d_lorient.py, moteurs INTACTS) :
  1) natif ∈ [−0.5, 3 m) & ATL100 ≥ 6 m → valeur ATL100 (1 068 cellules) ;
  2) rebouchage lacunes aussi quand ATL100 ≥ 6 m (passes étroites flanquées
  de bancs réels). Puis rm bathy_lorient_orig.npy + re-bake îles.
- Résultat : chenal Jument↔Citadelle CONTINU à seuil 2 m (carte vérifiée),
  Kernével↔Larmor OK (3 555 m), Kernével↔grand chenal OK, large→port OK.
- RESTE (moteur, PAS touché sans GO) : routes longues (>~10 km) via Lorient
  échouent encore (fenêtre grossière min-pool ferme le chenal 100-250 m à la
  passe décimée, ex. Kergroise→SE Groix bloqué 47.7099,-3.3686) ; extrémités
  réellement asséchantes à ZH (anse Port-Louis/Locmalo) = comportement normal
  (marée requise). Diagnostic complet livré à l armateur (fichiers npy,
  land_mask cuit à l ingestion jamais lu au runtime, log des rejets).

## ✅ ITER145 (27/08) — CORRECTIF BALISAGE LATÉRAL (GO armateur, données uniquement)
- Régression iter144 (wrong_side N° 3 / Banc du Turc à draft 1.0) : cause = le
  nettoyage « fausse surface » écrasait de VRAIES sondes de banc (natif
  1.5-2.9 m remplacé par ATL100 lissé ≥ 6 m, maille 100 m moyennant banc et
  chenal) au bord du balisage → l'A* et l'audit ne voyaient plus le banc.
- Fix ARMATEUR (aucun code moteur touché) :
  1) ``bathy_lorient_orig.npy`` (bake original 26/08) RESTAURÉ comme base ;
  2) ``scripts/patch_bathy_lorient_fausses_surfaces.py`` : patch CHIRURGICAL
     de 228 cellules explicites (fausses surfaces + lacunes d'axe du chenal,
     valeur = ATL100), IGNORANT tout ce qui est à < 200 m des bouées N° 3 et
     Banc du Turc, signature vérifiée (base NaN ou ∈ [−0.5, 3 m)), idempotent,
     re-cuit le masque terre → ``bathy_lorient.npy`` ;
  3) ``ingest_litto3d_lorient.py`` garde la règle générale équivalente pour
     toute future ré-ingestion (portes de chenal balisé : correction « eau
     profonde » licite uniquement ENTRE une latérale bâbord et sa tribord la
     plus proche, appariement au plus proche, couloir ± 200 m, cœur hors 25 m
     des bouées) — a produit exactement les mêmes 228 cellules.
- Tests : iter143 Moteur H 8/8 ✓ (calage pointillés + wrong_side vide),
  iter144 passes 5/6 ✓, îles 22/22 ✓, perf 4+1 xfail ✓.
- RESTE (PRÉ-EXISTANT, prouvé identique sur la grille 26/08 donc PAS une
  régression bathy) : ``test_bug_c_engine_h_official_tracks`` (draft 1.5)
  échoue — l'alignement OSM 711666732 traverse le banc du Turc (sondes
  réelles 1.4-2.3 m ≥ seuil d'écrêtage 0.5 m de core/safe_routes.py) et le
  Moteur H insère les pointillés tels quels → passage à l'EST des tribord.
  Correction possible côté moteur uniquement (écrêtage fonction du tirant
  d'eau) : EN ATTENTE DU GO ARMATEUR.

## ✅ ITER146 (27/08) — GEL DU MOTEUR F + CRÉATION DU MOTEUR I (ordre armateur)
- ⛔ RÈGLE ABSOLUE PERMANENTE : ``core/nav/engine_f_frozen.py`` NE DOIT PLUS
  JAMAIS ÊTRE MODIFIÉ (Moteur F = référence immuable validée support).
  Idem pour les modules figés A-E (signalmar_v1..v5) et signalmar_v6
  (base des Moteurs G/H — toute évolution v6 casserait le gel implicite).
- ``core/nav/engine_f_frozen.py`` : copie intégrale de la logique Moteur F
  (sidefix.py + signalmar_v6/__init__.py fusionnés, classe ``EngineFFrozen``,
  algo ``signalmar.f_frozen``). ``routers/routing.py`` (_resolve_algo local)
  force engine_f → algo gelé quel que soit le binding DB ; engine_f ajouté à
  FROZEN_ENGINE_IDS + rebind seed (algo signalmar.f_frozen en base).
- ``core/nav/engine_i.py`` : Moteur I (``EngineI``, algo ``signalmar.i``,
  doc ``engine_i`` « Moteur I travail 27.08.26 ») = duplicata exact du gelé.
  TOUTES LES FUTURES AMÉLIORATIONS/CORRECTIONS DE ROUTAGE SE FONT SUR
  ``core/nav/engine_i.py`` (jamais sur F ni sur v1-v6).
- Sélecteur mobile : dynamique (GET /api/routing/engines) → Moteur I visible.
- VÉRIFIÉ : 2 routes de référence (Lorient large→port 8862,5 m ;
  Arradon→La Trinité 22084 m) — résultats F gelé ≡ Moteur I ≡ ancien v6,
  100 % identiques hors ``compute_s`` (temps de calcul, volatil).
  Suites iter140/143/144 : 19 passed + 1 xfailed.
