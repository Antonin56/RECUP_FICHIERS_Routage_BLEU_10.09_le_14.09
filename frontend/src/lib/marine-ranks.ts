// SignalMar — Marine Nationale rank ladder.
// Used by the Profile screen to render an inspirational grades modal that
// shows every rank in order, highlights the current one, and motivates the
// user to keep logging sea-time (Phase H — miles + sorties → points).
//
// Point thresholds follow the Phase H scoring rule (cahier des charges):
//   - 1 confirmed sortie ≥ 1h on water = 1 point per hour, capped at 12/day.
// The ladder is intentionally generous at the start (Mousse, Matelot) and
// stretches at the higher grades to keep long-term motivation.
//
// Each rank carries an Ionicons name + accent colour for the badge UI.

export interface MarineRank {
  id: string;
  /** French name as used by the Marine Nationale. */
  label: string;
  /** Inclusive minimum point count required to unlock this grade. */
  min_points: number;
  /** Single-line motivational tagline shown next to the row. */
  tagline: string;
  /** Ionicons name (chevron family + crowns/stars). */
  icon: string;
  /** Accent colour — used for badge tint + row left bar. */
  color: string;
}

export const MARINE_RANKS: MarineRank[] = [
  { id: "mousse", label: "Mousse", min_points: 0, tagline: "Bienvenue à bord.", icon: "boat-outline", color: "#90E0EF" },
  { id: "matelot", label: "Matelot", min_points: 24, tagline: "Premiers quarts validés.", icon: "boat", color: "#90E0EF" },
  { id: "qm2", label: "Quartier-maître 2ᵉ classe", min_points: 60, tagline: "On commence à vous connaître.", icon: "compass", color: "#48CAE4" },
  { id: "qm1", label: "Quartier-maître 1ʳᵉ classe", min_points: 120, tagline: "Vigie fiable, signalements précis.", icon: "compass", color: "#48CAE4" },
  { id: "second_maitre", label: "Second maître", min_points: 240, tagline: "L'expérience commence à parler.", icon: "ribbon", color: "#00B4D8" },
  { id: "maitre", label: "Maître", min_points: 420, tagline: "Référence du bord.", icon: "ribbon", color: "#00B4D8" },
  { id: "premier_maitre", label: "Premier maître", min_points: 660, tagline: "Confirmé. La mer vous connaît.", icon: "ribbon", color: "#0096C7" },
  { id: "maitre_principal", label: "Maître principal", min_points: 960, tagline: "Vous entraînez les autres.", icon: "trophy", color: "#0096C7" },
  { id: "major", label: "Major", min_points: 1320, tagline: "Pilier de la communauté.", icon: "trophy", color: "#0077B6" },
  { id: "aspirant", label: "Aspirant", min_points: 1740, tagline: "Officier en devenir.", icon: "school", color: "#0077B6" },
  { id: "ev2", label: "Enseigne de vaisseau 2ᵉ classe", min_points: 2220, tagline: "Premier galon doré.", icon: "school", color: "#023E8A" },
  { id: "ev1", label: "Enseigne de vaisseau 1ʳᵉ classe", min_points: 2760, tagline: "Maître à bord en mer ouverte.", icon: "school", color: "#023E8A" },
  { id: "lv", label: "Lieutenant de vaisseau", min_points: 3360, tagline: "Navigateur confirmé.", icon: "medal", color: "#FFB703" },
  { id: "cc", label: "Capitaine de corvette", min_points: 4020, tagline: "On confie un commandement.", icon: "medal", color: "#FFB703" },
  { id: "cf", label: "Capitaine de frégate", min_points: 4740, tagline: "Vous menez les vôtres.", icon: "medal", color: "#FB8500" },
  { id: "cv", label: "Capitaine de vaisseau", min_points: 5520, tagline: "Commandant de bâtiment majeur.", icon: "medal", color: "#FB8500" },
  { id: "contre_amiral", label: "Contre-amiral", min_points: 6360, tagline: "Étoile d'argent.", icon: "star", color: "#FFD166" },
  { id: "vice_amiral", label: "Vice-amiral", min_points: 7260, tagline: "Le large s'incline.", icon: "star", color: "#FFD166" },
  { id: "vae", label: "Vice-amiral d'escadre", min_points: 8220, tagline: "Vous commandez une escadre.", icon: "star", color: "#FFC300" },
  { id: "amiral", label: "Amiral", min_points: 9240, tagline: "Sommet de la hiérarchie active.", icon: "star", color: "#FFC300" },
  { id: "amiral_de_france", label: "Amiral de France", min_points: 10320, tagline: "Dignité historique — quasi-mythique.", icon: "ribbon", color: "#E63946" },
];

export function rankForPoints(points: number): MarineRank {
  let current = MARINE_RANKS[0];
  for (const r of MARINE_RANKS) {
    if (points >= r.min_points) current = r;
    else break;
  }
  return current;
}

export function nextRank(points: number): MarineRank | null {
  const idx = MARINE_RANKS.findIndex((r) => r.min_points > points);
  return idx >= 0 ? MARINE_RANKS[idx] : null;
}
