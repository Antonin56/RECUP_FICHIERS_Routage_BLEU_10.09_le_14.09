#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================
backend:
  - task: "Moteur D (signalmar.v4) — sens conventionnel des latérales ISOLÉES + jamais de levée des côtés fiables"
    implemented: true
    working: "NA"
    file: "backend/core/seamarks.py, backend/core/routing_engines/algos/signalmar_v4/__init__.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          Bug armateur 10/08 : route Moteur D Golfe→Vilaine (mode « eau peu
          profonde ») laissait No1 (9,8 m), No11, Jument du MAUVAIS côté.
          Cause : _run_shallow/_last_resort (routers/routing.py) arment
          SIDE_RULES_OPEN qui levait TOUTES les zones de côté latérales dans
          rasterize_blocked. Correctif : sous ISOLATED_SIDE_BATHY (armé
          uniquement par signalmar.v4/Moteur D), les latérales à direction
          FIABLE (couple/override/asymétrie bathy) ne sont JAMAIS levées.
          Moteurs A/B/C strictement inchangés (contextvar + caches séparés).
          Vérifié localement : même route → wrong_side_marks vide, distance
          51,1 km. Tests pytest 9/9 (iter133) + régressions B/C 24/24.

test_plan:
  current_focus:
    - "Moteur D (signalmar.v4) — sens conventionnel des latérales ISOLÉES + jamais de levée des côtés fiables"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: >
      ITER147 (31/08) : tester UNIQUEMENT le backend (routing). Nouveau :
      Moteur I (engine_i) = routes officielles écrêtées au tirant d'eau +
      doublon « Les Errants » neutralisé. Fichier modifié : SEUL
      backend/core/nav/engine_i.py. Lancer pytest
      tests/test_iter147_moteur_i_ecretage.py + régressions
      iter143/144/140/136 (gel moteurs A-H). Auth : email
      antoninlepinay@gmail.com / mdp 123454321 (ou OTP 0760071445 / 123456) ;
      header X-RateLimit-Bypass: qa-bypass-signalmar-2026. Les calculs de
      route peuvent prendre 1-3 min (timeout large). NE PAS modifier
      engine_f_frozen.py ni les algos signalmar_v1..v6/h (moteurs gelés).
  - agent: "main"
    message: >
      Tester UNIQUEMENT le backend (routing). Auth : OTP phone 0760071445 /
      code 123456 (dev bypass) ou password 123454321 ; header
      X-RateLimit-Bypass: qa-bypass-signalmar-2026 pour éviter le rate-limit.
      Les calculs de route peuvent prendre 1 à 3 min (timeout large requis).

  - task: "Moteur D — résidu Illur en marge AUTO (10 m) : passe 3 (redressement) recoupait le mauvais côté"
    implemented: true
    working: "NA"
    file: "backend/core/seamarks.py (clearance_points)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          Résidu identifié par le testing agent (iteration_1.json) : en marge
          AUTO (10 m), _straighten/_repair (_corridor_safe, passe 3) ne
          contrôlent que fond + portes + cercles d'écart 60 m → le tracé
          était retendu au SUD d'Illur à 91 m. Fix : sous ISOLATED_SIDE_BATHY
          (Moteur D seulement), clearance_points couvre le demi-disque danger
          (200 m) des latérales ISOLÉES à côté fiable par un semis de disques
          d'écart (3 anneaux × 5 azimuts, r=45 m). Vérifié localement :
          Illur NORD dans les 2 sens à marge 10 (121 m / 81 m), Vilaine eau
          peu profonde toujours sans wrong_side. Suites 19/19 + 35/35.
          Aussi corrigé : backend/.env ligne collée SMS_PROVIDER/RATE_LIMIT.

  - task: "Moteur E (signalmar.v5) — côté absolu, couples réciproques, plafond densité, arrivée jamais tronquée (Crouesty) + édition waypoint unique (frontend)"
    implemented: true
    working: "NA"
    file: "backend/core/seamarks.py, backend/core/routing_engines/algos/signalmar_v5/__init__.py, frontend/app/(tabs)/map.tsx, frontend/src/components/marine-map/js/route.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          Consignes armateur 11/08 : Moteur D FIGÉ ; nouveau Moteur E
          (engine_e → signalmar.v5). Corrigés : (1) couple écarté chenal de
          Vannes (rouge recoupée à 139 m) — demi-disque PLEIN ≤ 0,8×gap ;
          (2) arrivée Crouesty refusée (944 m) — couples RÉCIPROQUES (faux
          couples des coudes supprimés), plafond de DENSITÉ des rayons,
          complétion d'arrivée (A* marée puis SUIVI DU CHENAL BALISÉ,
          tronçons rouges + risk). AUCUNE exception de terrain (overrides
          supprimés). Frontend : édition de route = seul le waypoint le plus
          proche du toucher est déplaçable (les autres = repères), bouton
          « Recalculer la route » après déplacement (manualRoute avec le
          moteur de la route affichée). Tests locaux : itér.133 19/19 (D
          figé conforme), Crouesty end_snapped=None + rouges, Grand Mouton
          bon côté, Illur nord 2 sens.

  - task: "Iter136 — Moteur F (signalmar.v6) : Truie d'Arradon bon côté, chenal La Trinité respecté (N°4/N°8/N°12), plus de Z, arrivée atteinte ; Moteur E FIGÉ"
    implemented: true
    working: true
    file: "backend/core/routing_engines/algos/signalmar_v6/__init__.py, backend/core/routing_engines/algos/signalmar_v6/sidefix.py, backend/core/seamarks.py (SIDE_ABSOLUTE_V6), backend/tests/test_iter136_moteur_f_trinite_truie.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          Consignes armateur 13/08 : Moteur E FIGÉ (copie → Moteur F,
          engine_f/signalmar.v6). Bugs (route R-20260813-144317-MX, Arradon →
          La Trinité, marge 30, seuil 1,5, marée 0) : Truie d'Arradon mauvais
          côté 165 m malgré warning ; N°4 frôlée 0,7 m ; N°8 mauvais côté
          129 m ; Z ; arrivée manquée de 98 m sans flag. Fix v6 UNIQUEMENT :
          sidefix (réparation géométrique mauvais côtés par re-calcul local +
          insertion bon côté, frôlements deux-seuils, lissage épingles>100°),
          complétion disciplinée par le balisage (extension A* rejetée si
          violation → chaîne du chenal, reliquat géométrique, recul d'ancre).
          Local : iter136 10/10, iter135 5/5, iter134 5/5, iter133+129+126
          57 verts. E2E async API engine_f OK. Moteur E strictement identique
          à la route MX stockée (gel prouvé).
      - working: true
        agent: "testing"
        comment: >
          iteration_3.json — 32/32 verts : iter136 10/10, E2E API async
          engine_f 3/3 (wrong_side vide, arrivée exacte, algo signalmar.v6
          6.1.0), gel Moteur E prouvé (Truie toujours flaguée, 22,6 km),
          régressions iter133/134/135 19/19. Aucun bug détecté.

  - task: "Iter137 — Moteur F : plafond cardinale (chenal Truie/Druic emprunté, routes convergentes) + purge warnings obsolètes + bouton « Signaler un balisage non respecté » (RouteCard + API mark-report)"
    implemented: true
    working: true
    file: "backend/core/seamarks.py (cap cardinal SIDE_ABSOLUTE_V6), backend/core/routing_engines/algos/signalmar_v6/__init__.py, backend/routers/routing.py (mark-report), frontend/src/components/RouteCard.tsx, frontend/src/api/client.ts, backend/tests/test_iter137_cardinale_chenal.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          Bugs armateur 14/08 : B5 détour 1 km par le nord (cardinale N à
          114 m de la Truie scellait le chenal en maille 100 m), CT
          divergente. Fix : rayon mauvais-côté cardinal plafonné à 0,9 ×
          latérale la plus proche (gated SIDE_ABSOLUTE_V6) ; purge+ré-audit
          des warnings de frôlement après fusion. Feature : bouton flag sur
          RouteCard → POST /api/routes/mark-report (snapshot auto) + GET
          /api/routes/mark-reports. Local : iter137 6/6, iter136 10/10,
          régressions 60 verts, curl mark-report OK (BR-…).
      - working: true
        agent: "testing"
        comment: >
          iteration_4.json — backend 35/35 (iter137 6/6 + iter136 10/10 +
          régressions 14/14 + e2e API signalement 5/5 : B5 22 739 m via le
          chenal court, wrong_side vide, mark-report BR-… OK) ; frontend :
          bouton RouteCard → modal → envoi vérifié en préview web (toast +
          doc en base avec engine_id/route_id joints). Aucun bug.

  - task: "Iter138 — audit QA : P0 tronçon sur terre (Moteur F), gel réel moteurs A-E, 404 moteur inconnu, job relisible, dev-switch gated env, login email UI, géofiltre carte, codes d'erreur API, anti double-tap signalement"
    implemented: true
    working: true
    file: "backend/core/routing_engines/algos/signalmar_v6/__init__.py, backend/core/routing_engines/manager.py, backend/routers/{routing,routing_engines,auth,notifications,bathy,reports,diagnostics,dev_switch}.py, backend/tests/test_iter138_audit_qa.py, frontend/app/(auth)/login.tsx, frontend/app/(tabs)/map.tsx, frontend/src/{auth/AuthContext.tsx,api/client.ts,components/{RouteCard.tsx,ReportSharePreview.tsx}}"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          Lot audit QA. Local : iter138 4/4, régressions 30 verts, curls OK
          (frozen refusé, 404 moteur inconnu, 422 bbox, 404 recompute).
          Décisions armateur : pas de reset mot de passe, pas d'Europe,
          Moteur D intact. ALLOW_DEV_SWITCH="true" ajouté à backend/.env
          (à NE PAS copier en prod).
      - working: true
        agent: "testing"
        comment: >
          iteration_5.json — pytest 20/20 + e2e URL publique 16/16 (gel A-E,
          404 moteur inconnu, job relisible x2, P0 arrivee_a_terre min -1.5,
          E garde son bug (gel), codes 400/422/404, duplicate=true) ;
          frontend : login email OK, RouteCard astuce + signalement OK.
          Aucun bug. Note : URL publique de préview = engine-e-crouesty.

  - task: "Iter139 — Moteur F : balises de chenaux respectées (Lorient/Croisic/Kerpenhir) + zones rouges PRÉCISES cliquables (info hauteur d'eau + options route)"
    implemented: true
    working: "NA"
    file: "backend/core/seamarks.py (mark_dir_confident v6 : cache v5 ne court-circuite plus le mode V6, faux couple corrigé par consensus des voisines), backend/core/routing_engines/algos/signalmar_v6/sidefix.py (validation limitée aux segments modifiés, passes côtés/frôlements rejouées, infractions préexistantes non bloquantes via ref, variante épinglée sur longs bords), backend/tests/test_iter139_directions_chenaux.py, frontend/src/components/marine-map/js/route.ts (zones rouges depuis depth_profile + tap → route_tap avec danger), frontend/src/components/MarineMap.tsx (RouteTapDanger), frontend/app/(tabs)/map.tsx (bandeau danger dans le menu route), frontend/src/screens/map/map-styles.ts"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          Bugs armateur 25/08 (balises de chenal non respectées). 5 causes
          racines corrigées (gated v6) : 1. cache _dir_conf_v5 court-
          circuitait le bloc V6 (Kerpenhir/Rouzins jamais héritées) ;
          2. validation d'insertion incluait des segments INCHANGÉS déjà
          rouges → toutes réparations rejetées ; 3. les phases côtés/
          frôlements ne se rejouaient pas (réparations interdépendantes
          N°3 → Banc du Turc) ; 4. faux couple N°4-N°3 (dir SW) corrigé
          par consensus des voisines ; 5. Écrevisse : longs bords réparés
          par variante « épinglée » + infractions préexistantes (épave à
          38 m) non bloquantes. Résultat : route Lorient = 0 mauvais côté
          (avant : 6). Local : 26/26 verts (iter136-139). Baseline git
          stash confirmée : les 12 échecs e2e (iter101/103/104, OTP 429)
          sont PRÉEXISTANTS au fork, pas causés par ces correctifs.
          Feature : zones ROUGES PRÉCISES sur la carte (échantillons du
          depth_profile < seuil, plus le tronçon entier) ; tap sur une
          zone rouge → menu route AVEC bandeau « Hauteur d'eau
          insuffisante ici : fond mini ~X m pour un besoin de Y m »
          (testID route-menu-danger) ; tronçon entier conservé en rouge si
          raison low_margin ou profil muet (fallback).
      - working: true
        agent: "testing"
        comment: >
          iteration_6.json — backend : pytest 26/26 (iter136-139) + e2e URL
          publique 3/3 (Lorient F wrong_side vide ~8,8 km, E gelé OK,
          depth_profile + threshold_m présents). Frontend (390x844, login
          email) : tap zone rouge → modal « Route sûre » AVEC bandeau
          route-menu-danger (« Hauteur d'eau insuffisante ici, fond mini
          ~X m ») + toutes les options ; tap route normale → modal SANS
          bandeau. Aucun bug bloquant. Notes API : job = /api/routes/job/{id},
          champ login = token, testID submit = login-email-submit.

  - task: "Iter140 — refactor map.tsx : constantes + helpers purs + 13 modals extraits sous src/screens/map/ (déplacement pur, zéro changement fonctionnel)"
    implemented: true
    working: true
    file: "frontend/app/(tabs)/map.tsx (4774→4125 lignes), frontend/src/screens/map/map-constants.ts, frontend/src/screens/map/route-geometry.ts, frontend/src/screens/map/modals/{UnitPickerModal,BathyOpacityModal,AnchorModal,LongPressMenuModal,AlertSettingsModal,LowMarginModal,SaferPreviewModal,RiskConfirmModal,RouteMenuModal,RouteChoiceModal,SaveRouteNameModal,SeamarkInfoModal}.tsx, frontend/src/components/MarineMap.tsx (type danger du message route_tap)"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          Refactor demandé par l'armateur (backlog approuvé iter138).
          Extraction par plages de lignes (script python bottom-up avec
          garde-fous par jeton), tous les testIDs conservés. tsc : 0 erreur
          dans les nouveaux fichiers, baseline 25 erreurs préexistantes → 24
          (une corrigée : type danger MarineMap). Imports morts retirés
          (GestureHandlerRootView, AnchorPanel).
      - working: true
        agent: "testing"
        comment: >
          iteration_7.json — 10/10 flux OK via simulation MessageEvent
          (longpress menu, choix de route, barre manuelle, menu route ±
          bandeau danger, enregistrement, fiche balise, ancre, unités).
          AlertSettingsModal gaté par un `false &&` PRÉEXISTANT (décision
          armateur) — vérifié par revue de code. Aucune régression.

  - task: "Iter141 — perf : calcul de route < 10 s (numba A* JIT + cache rasterisation v6 + ZH/marée en parallèle)"
    implemented: true
    working: true
    file: "backend/requirements.txt (numba/llvmlite), backend/core/seamarks.py (RASTER_CACHE + cache rasterize_blocked), backend/core/routing_engines/algos/signalmar_v6/__init__.py (cache armé par calcul), backend/routers/routing.py (_run margin_box, _run_zh_tide parallèle), backend/tests/test_iter140_perf_route_10s.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          3 leviers : (1) numba installé → le cœur A* JIT (_astar_nb, prévu
          par conception, commentaire 27/07 « hyper lent comparé à
          Navionics ») est ACTIF : _astar_py 9,9 s → ~0,3 s ; (2) cache de
          rasterize_blocked par fenêtre, contextvar RASTER_CACHE gated v6
          (A-E : défaut None, inchangés) — 252 rasterisations/calcul ;
          (3) endpoint : ZH et marée en PARALLÈLE (asyncio.gather), suivi
          de marge par margin_box (plus de nonlocal partagé), sémantique
          28/07 inchangée. Lorient→Golfe (pire cas, cascade ZH+marée+eau
          peu profonde) : ~30 s user / 16,2 s mesuré → 8,1 s.
          Lorient→Trinité : 2,2 s → 1,3 s.
      - working: true
        agent: "testing"
        comment: >
          iteration_8 — PERF 5/5 : Golfe 8,30 s (<10) ✓, Trinité 1,56 s ✓,
          iter139 wrong_side vide ✓, Moteur E OK ✓, warm-up 1,47 s.
          Non-régression : 26/26 balisage + 40/40 moteurs gelés (série).
          Échecs OTP 410 en xdist parallèle = artefact env connu.

  - task: "ITER145 — Correctif balisage latéral (patch chirurgical bathy Lorient)"
    implemented: true
    working: true
    file: "backend/scripts/patch_bathy_lorient_fausses_surfaces.py"
    status_history:
      - working: true
        agent: "main"
        comment: >
          Ordre armateur : bathy_lorient_orig.npy (26/08) restauré comme base ;
          patch chirurgical de 228 cellules explicites (fausses surfaces +
          lacunes du chenal, valeur ATL100), exclusion < 200 m des bouées
          N° 3 / Banc du Turc, signature vérifiée, idempotent, masque terre
          re-cuit. Grille résultante bit-identique au bake « portes de chenal »
          validé. Tests : iter143 8/8, iter144 5/6, îles 22/22, perf OK.
          Seul échec restant = test_bug_c_engine_h_official_tracks (draft 1.5),
          PRÉ-EXISTANT (reproduit à l'identique sur la grille 26/08) :
          l'alignement OSM 711666732 traverse le banc du Turc (sondes réelles
          1.4-2.3 m > seuil d'écrêtage 0.5 m) — correction côté moteur
          uniquement, en attente GO armateur.

  - task: "ITER153 — Moteur I v7.4.0 : seuil de redressement 80 m + cardinales à la règle carte (secteur + écart 50 m) — engine_i.py uniquement"
    implemented: true
    working: "NA"
    file: "backend/core/nav/engine_i.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          GO armateur points 1+2 : _DETOUR_GAIN_M 500→80 m (tout zigzag
          redressé si corde sûre) ; écart minimal étendu aux cardinales
          (max(50 m, écart recommandé), repoussement radial validé) ;
          _cardinal_ok (bon secteur, 200 m) appliqué aux cordes du
          redressement, du bypass Errants et aux segments repoussés.
          Objectif : effacer les artefacts de maille (goulot Creizic Sud,
          Berder → Roguedas). AUCUN calcul exécuté (ordre armateur).
          Backend redémarré.


    implemented: true
    working: "NA"
    file: "backend/core/nav/engine_i.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          Bug armateur Golfe/Creizic Sud : détour de plusieurs km selon un
          départ décalé de 10 m (couloir A* élu à la maille, F gelé).
          Fix post-traitement déterministe : _shortcut_large_detours (corde
          directe si détour > 500 m ET corde strictement sûre ; secteur des
          cardinales contrôlé via _cardinal_ok à 200 m ; fond jamais
          dégradé ; 3 passes, plus grand détour d'abord). Câblé entre le
          bypass Errants et l'écart latéral 50 m. AUCUN calcul exécuté
          (ordre armateur — il reteste les 2 routes sur la carte).
          Backend redémarré.


    implemented: true
    working: "NA"
    file: "backend/core/nav/engine_i.py, backend/tests/test_iter147_moteur_i_ecretage.py (assertions mises à jour)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          3 règles globales armateur 01/09 : (1) homonymes ≤ 500 m → la
          latérale ambiguë (blanche OU couleur inconnue) ignorée, référence
          = conforme rouge/verte ou cardinale ; (2) wrong_side purgé puis
          rejoué sous cohérence de direction (faux couples corrigés → plus
          de fausse alerte Petite Jument/No2 du bon côté) ; (3) frôlement
          latéral < max(50 m, écart recommandé) → point repoussé
          radialement si le tracé modifié est strictement sûr, sinon F tel
          quel. AUCUN calcul exécuté (ordre armateur). Backend redémarré.
          Testing agent à lancer après validation carte.


    implemented: true
    working: "NA"
    file: "backend/core/nav/engine_i.py (v7.1.0), backend/tests/test_iter147_moteur_i_ecretage.py (réécrit), test_iter148_e2e_armateur.py (supprimé)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          Bug armateur : I +9,3 km vs F avec zigzags (Port-Navalo → SW
          Belle-Île) — le planificateur hérité de H accrochait des chenaux
          à ≤ 3 km de la ligne directe. Ordre : supprimer intégralement le
          suivi des pointillés du Moteur I. Fait : compute_auto = F pur +
          bypass/strip Errants ; _compute_with_tracks/_network_i/
          _plan_tracks_i/_join_endpoints_i/_wrong_side_i/_data_gap_only
          supprimés. AUCUN calcul de test exécuté (ordre armateur — il
          teste sur la carte) ; seuls compilation + import vérifiés.
          Backend redémarré. Testing agent À LANCER après validation carte
          de l'armateur.


    implemented: true
    working: "NA"
    file: "backend/routers/routing.py (bloc jobs uniquement)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          Bug armateur en production : le dict _JOBS vivait en mémoire de
          process → avec plusieurs instances backend, le GET /api/routes/job
          tombait sur une autre instance que le POST → 404 « Calcul
          introuvable (expiré) ». Fix : jobs dans la collection Mongo
          route_jobs (_id=job_id, uid, status, ts datetime UTC, result/
          detail), index TTL ts 900 s (créé idempotent au 1er usage), _job_
          start/_job_run/routes_job réécrits en lecture/écriture base ;
          _JOBS/_jobs_gc/_JOBS_MAX supprimés ; _JOB_TASKS (réfs fortes
          asyncio) conservé. Smoke local : POST async → done dist 8922,2 ;
          relecture OK (FND-012) ; job inconnu → 404 ; index TTL vérifié en
          base. Moteurs et engine_i.py NON touchés. POST-VALIDATION :
          await manquant sur _job_start dans recompute_saved_route_async
          (signalé par le testing agent) corrigé puis vérifié e2e
          (recompute async → done). Validé testing agent
          (iteration_14 : 5/5 + régression iter147 8/8).


    implemented: true
    working: "NA"
    file: "backend/core/nav/engine_i.py (seul fichier code), backend/tests/test_iter147_moteur_i_ecretage.py (2 tests ajoutés)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          GO armateur : baseline = Moteur F GELÉ (pas H). (1) Hors routes
          officielles, Moteur I calcule en MODE F PUR → tracé identique à F
          (vérifié Arradon→Lorient 66 km). (2) Assemblage refusé → repli F
          (plus jamais de cascade « eau peu profonde »). (3) Détour fantôme
          du doublon Les Errants supprimé par bypass géométrique validé
          (fond/portes/frôlements/latérales/mouillages + fond jamais
          dégradé) : 1690→1625 m, vraies roches toujours contournées.
          (4) Écrêtage au besoin d'eau étendu aux tracés chartés + jonctions
          contrôlées bathy (cellules −0,67 m devant Kernével). (5) Faux
          tronçons rouges éliminés : audits rejoués sur tracé final + filtre
          lacunes NaN ≤ 60 m (warning honnête). Comparaison Lorient :
          F=8862 m/3,07 m/2 mauvais côtés ; I=8922 m/7,38 m/0 mauvais
          côté/0 rouge. iter147 8/8 vert.


    implemented: true
    working: "NA"
    file: "backend/core/nav/engine_i.py (seul fichier modifié), backend/tests/test_iter147_moteur_i_ecretage.py (nouveau)"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: >
          GO armateur 31/08 : le Moteur I gagne le suivi des routes
          officielles (logique Moteur H copiée, H INCHANGÉ) mais le réseau
          des pointillés est écrêté au BESOIN D'EAU RÉEL (tirant + marge −
          marée, plancher 0,5 m, cache par pas de 0,1 m) — mesuré : ~20 km
          d'alignements < 2 m de fond conservés par H sont retirés chez I
          (ex. Passe Ouest Lorient way 736 : 3878 → 3636 m, fond 0,65 m).
          Doublon « Les Errants » ANALYSÉ : tourelle blanche id 1421434210
          (couleur contredit la catégorie bâbord) + bouée rouge id
          1421434206 à 351 m, côtés requis v6 divergents de ~82° → règle
          Moteur I : latérale de couleur contradictoire doublée d'une
          homonyme conforme ≤ 600 m = plus de règle de CÔTÉ (écrêtage +
          audit wrong_side filtré), écart minimal 60 m conservé. Les
          perches génériques sans couleur ne sont PAS neutralisées (faux
          positifs écartés). LIMITE documentée : le détour du tracé imposé
          par le demi-disque rasterisé de la blanche (seamarks.py) reste —
          correction possible uniquement hors périmètre (GO armateur
          requis). Import circulaire safe_routes→v4→algos→engine_i corrigé
          (accès attributs différés). Local : iter147 6/6, iter143 8/8,
          iter144 6/6, iter140+136 14/14+xfail, iter137/139/133/îles 53
          verts. Moteurs A-H strictement inchangés (aucun autre fichier
          touché).


    implemented: true
    working: true
    file: "backend/core/nav/engine_f_frozen.py, backend/core/nav/engine_i.py, backend/routers/routing.py, backend/core/routing_engines/manager.py"
    status_history:
      - working: true
        agent: "main"
        comment: >
          Moteur F gelé (copie intégrale sidefix+v6, algo signalmar.f_frozen,
          engine_f forcé vers le fichier gelé dans routing.py + frozen=True en
          base). Moteur I créé (duplicata exact, algo signalmar.i, doc
          engine_i), visible dans le sélecteur mobile (liste dynamique).
          RÈGLE ABSOLUE : ne plus jamais modifier engine_f_frozen.py ; toutes
          les évolutions de routage sur engine_i.py. Vérifié : 2 routes de
          référence F≡I≡ancien v6 100% identiques (hors compute_s volatil) ;
          iter140/143/144 : 19 passed + 1 xfailed.
