// SignalMar — constantes de l'écran carte.
// Découpé de app/(tabs)/map.tsx le 27/08/2026 (refactor map.tsx) :
// déplacement PUR, aucun changement fonctionnel.

// 22/07/2026 — libellés FR des objets cliquables (balises + dangers).
export const SEAMARK_KIND_LABEL: Record<string, string> = {
  lateral: "Balise latérale",
  cardinal: "Balise cardinale",
  isolated_danger: "Danger isolé",
  special: "Marque spéciale",
  safe_water: "Eaux saines",
  rock: "Roche",
  wreck: "Épave",
  obstruction: "Obstruction",
  // 26/07 — bouées de mouillage cliquables (zones évitées par le routeur).
  mooring: "Bouée de mouillage",
};
export const SEAMARK_CAT_LABEL: Record<string, string> = {
  port: "Bâbord (rouge) — laisser à bâbord en entrant",
  starboard: "Tribord (verte) — laisser à tribord en entrant",
  north: "Nord — passer au NORD de la balise",
  south: "Sud — passer au SUD de la balise",
  east: "Est — passer à l'EST de la balise",
  west: "Ouest — passer à l'OUEST de la balise",
  dangerous: "Épave DANGEREUSE pour la navigation",
  "non-dangerous": "Épave non dangereuse",
  hull_showing: "Coque visible",
  mast_showing: "Mât visible",
  distributed_remains: "Débris épars",
};
// Niveau d'eau des roches/obstructions (seamark:*:water_level OSM).
export const WATER_LEVEL_LABEL: Record<string, string> = {
  covers: "Couvrante/découvrante (couvre et découvre avec la marée)",
  awash: "À fleur d'eau",
  submerged: "Toujours submergée",
  always_dry: "Toujours émergée",
  dry: "Découvrante",
};

// Default centre: between the Golfe du Morbihan and Belle-Île.
export const DEFAULT_CENTER = { lat: 47.46, lng: -2.92 };

// Rayon d'AFFICHAGE des signalements (fixe, interne). L'ancien bouton
// « 200 km » en haut de la carte a été supprimé (10/07/2026) : il créait
// une confusion avec la Zone de veille. Tous les signalements dans ce
// rayon restent visibles ; seule la Zone de veille déclenche les alertes.
export const DISPLAY_RADIUS_KM = 200;
// Bascule AUTO Vigie ⇄ Navigation (11/07/2026) : le mode suit le bateau.
// ≥ 3 km/h maintenu 5 s → Navigation ; < 3 km/h maintenu 5 s → Vigie.
export const AUTO_SWITCH_SPEED_MS = 3 / 3.6; // 3 km/h en m/s
export const AUTO_SWITCH_SUSTAIN_MS = 5_000;
// Phase K — Navigation cone defaults & bounds.
export const CONE_ANGLE_DEFAULT = 45; // total spread in degrees (half-angle = 22.5)
export const CONE_ANGLE_MIN = 5;
export const CONE_ANGLE_MAX = 90;
// Longueur du cône Navigation = Zone de veille Navigation (valeur fixe
// choisie par l'utilisateur — l'ancienne formule vitesse × 10 min a été
// remplacée le 10/07/2026 : « Simple, sans ambiguïté »).
