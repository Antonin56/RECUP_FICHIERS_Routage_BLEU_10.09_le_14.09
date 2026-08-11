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
