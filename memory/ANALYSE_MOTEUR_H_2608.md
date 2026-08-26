# Analyse 26/08 — captures armateur « post mihir » + pertinence Moteur H
(AUCUN CODE ÉCRIT — analyse seule, feu vert armateur attendu)

## 1. Diagnostic par capture (routes engine_f 25-26/08, AVANT perf iter141)

### a) « Écart injustifié Belle-île Arradon sur Grand Mouton » (R-20260825-094132-WA)
- Zone PILOTE (MNT 20 m) → pas un problème de données.
- Cause : les réparations locales v6 (écart minimal / mauvais côté / frôlement)
  INSÈRENT un point de contournement puis rejoignent le tracé SANS passe de
  lissage a posteriori → « Z » résiduel. Idem raccords de fenêtres de
  raffinement (doglegs aux bords de fenêtre).
- Fait notable : une recommended_track OSM (pointillés Port-Navalo) passe
  exactement là — un moteur qui suit les routes officielles n'aurait pas ce Z.

### b/d) Lorient balises non respectées (R-20260826-100239-Z8 / -125556-PK)
- Lorient est HORS zone pilote : MNT 20 m s'arrête à lng -3.333 ; la rade
  (-3.35..-3.42) est sur ATL100 → maille réelle 75-110 m.
- Chenal large 150-250 m ≈ 1,5-2,5 cellules → application des côtés/écarts
  structurellement peu fiable à cette maille (déjà documenté ITER126) ;
  réparations rejetées ou partielles → passages à 7-9 m de balises SANS nom
  (« balise port/starboard » = tags OSM sans seamark:name).

### c) « Hauteur d'eau fausse » (fond mini -0,1 m, tronçons rouges)
- VÉRIFIÉ dans NOS données (ATL100) le long de l'axe balisé de Lorient :
  Passe Ouest 8,5 m ; jonction 10,3 m ; Citadelle 15-18 m ; chenal Ouest du
  Banc du Turc 6-9,5 m ; axe Pengarne 14-16 m. LE CHENAL EST DANS NOS DONNÉES.
- Le rouge vient du PLACEMENT de la route : la diagonale coupe les platiers
  réels (Banc du Turc assèche, Pengarne 1,8 m, seuils 2-4 m à 45-90 m de
  l'axe). À maille ~100 m, 1 échantillon hors axe suffit à peindre du rouge.
- Verdict : donnée globalement correcte, route pas assez « dans le chenal ».

## 2. Capacité actuelle de détection de routes sûres (avis objectif)
- Zone pilote (Morbihan, 20 m) : bonne — tracés corrects, défaut restant =
  zigzags cosmétiques des réparations locales.
- Hors zone pilote (ATL100 ~100 m) : structurellement limitée pour les
  chenaux étroits — inférer un chenal à partir de bathy 100 m + bouées est
  la partie la plus fragile du système ; itérer sur v6 a un rendement
  décroissant (iter126→139 en témoignent).

## 3. Détection des routes officielles — FAISABLE, MESURÉ (Overpass 26/08 réel)
OSM contient les ways seamark suivants (non ingérés aujourd'hui — on n'ingère
que des NŒUDS balises) :
- Lorient : 2 recommended_track (axes 57°/16,5° Passe Ouest/Sud),
  4 navigation_line (« Lignes B1..B5 »), 3 fairway dont polygones nommés
  « Passe du Sud », « Chenal d'Approche ».
- Golfe du Morbihan : 10 recommended_track + 9 navigation_line.
- Quiberon/Trinité : 8 ; Loire/St-Nazaire : 8 (dont 5 fairways) ;
  Brest/goulet : 2 ; **Douarnenez : 0** (couverture OSM inégale !).
Réserves techniques :
- navigation_line = ALIGNEMENT (ligne de visée vers un amer) : déborde la
  partie navigable, à ÉCRÊTER (par fairway/bathy/balises).
- Aucune profondeur taguée sur ces ways → l'audit bathy reste obligatoire
  sur la route calée (nos ATL100 reflètent bien les chenaux dragués : mesuré).
- Couverture communautaire inégale → repli « calcul classique » indispensable
  (déjà prévu par la spec armateur).

## 4. Avis sur le Moteur H : PERTINENT — recommandé, avec 3 ajustements
- Le principe « suivre les routes officielles quand elles existent » attaque
  la racine de 4 des 5 problèmes des captures (tout Lorient + Grand Mouton).
  C'est ce que font les skippers et le dock-to-dock Navionics.
- Ajustement 1 (architecture) : plutôt que « si route trouvée on la suit,
  sinon on calcule », intégrer les tracks comme COULOIRS À COÛT QUASI NUL
  dans l'A* → gère nativement « la plus courte », les jonctions
  entrée/sortie, et « si la route sûre ne va pas jusqu'à destination, la
  suivre au plus proche puis calculer la fin ».
- Ajustement 2 (règle 1 km cardinales/latérales) : OK comme hiérarchie de
  priorité (prolonge iter137 « la latérale fait autorité ») ; mais une
  cardinale reste un OBSTACLE à respecter même en présence de latérales —
  elle ne doit juste plus DÉTOURNER la route hors du couloir latéral.
- Ajustement 3 (« comparer la hauteur d'eau des 2 passages ») : fiable en
  zone pilote ; hors zone pilote (maille 100 m) c'est précisément là où la
  donnée est la plus faible → la priorité aux tracks officiels doit primer
  sur cette comparaison quand un track existe.
- Rayon paramétrable : trivial (param moteur côté engines, ajustable par
  API sans UI). Départ 1 km.
- Effort estimé : ingestion ways (nouveau script + collection), écrêtage des
  navigation_lines, greffe couloirs dans un moteur H gated (base F),
  tests A/B → 2-3 itérations. Moteurs A-F inchangés.
