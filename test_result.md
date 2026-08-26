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
