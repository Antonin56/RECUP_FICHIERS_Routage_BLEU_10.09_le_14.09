// SignalMar — Indice de fiabilité (0-100%).
// Mirror of the backend rules. Used by the profile pill + dedicated
// /profile/reliability page to render the score and tint badges by tier.

export const RELIABILITY_DEFAULT = 50;
export const RELIABILITY_MIN = 0;
export const RELIABILITY_MAX = 100;

export interface ReliabilityTier {
  label: string;
  color: string;
  icon: string;
  description: string;
}

// Five tiers tinted from grey (untrusted) → gold (reference vigie). Mirrors
// the colour palette already used for Marine Ranks for visual coherence.
const TIERS: ReliabilityTier[] = [
  { label: "Novice",     color: "#8D99AE", icon: "help-circle-outline",      description: "Tout juste arrivé à bord." },
  { label: "Apprenti",   color: "#48CAE4", icon: "checkmark-circle-outline", description: "Premiers signalements pris au sérieux." },
  { label: "Confirmé",   color: "#2A9D8F", icon: "shield-checkmark-outline", description: "La communauté confirme régulièrement vos alertes." },
  { label: "Référence",  color: "#FB8500", icon: "trophy-outline",           description: "Vos signalements pèsent lourd. Difficile à infirmer." },
  { label: "Vigie d'or", color: "#FFD166", icon: "star",                     description: "Le sommet — votre parole fait référence." },
];

export function reliabilityTier(pct: number): ReliabilityTier {
  const s = Math.max(RELIABILITY_MIN, Math.min(RELIABILITY_MAX, Math.round(pct)));
  if (s <= 20) return TIERS[0];
  if (s <= 40) return TIERS[1];
  if (s <= 60) return TIERS[2];
  if (s <= 85) return TIERS[3];
  return TIERS[4];
}

/** True for "high reliability" — used to decide whether to show the on-map badge. */
export function isHighReliability(pct: number | null | undefined): boolean {
  return typeof pct === "number" && pct >= 70;
}

/** Score is already a percentage (0-100), kept as a function so legacy callers
 *  (e.g. the reliability help page) keep working without refactor. */
export function reliabilityPct(score: number): number {
  return Math.max(RELIABILITY_MIN, Math.min(RELIABILITY_MAX, Math.round(score)));
}
