// SignalMar — Single source of truth for report types.
// Refonte v2 (cahier des charges 27/06/2026):
//   - 5 main types only: autorites, obstacle_nav, animal_marin, pollution, autre.
//   - Subtypes carry the drift physics (V/C weights 1..10) used by the drift-cone
//     algorithm (Phase B). Rules of thumb: containers float low → mostly current
//     (C=9). Floating wood is wind-prone (V=7). Marine birds drift with the wind
//     (V=8). Rocks never drift (drift = null → cone disabled).
//   - Subtypes can override the parent TTL (e.g. pollution_cote = 24h).
//   - `extras` signals the UI to ask additional contextual questions
//     (e.g. health state for an animal, variant for a rock).

import type Ionicons from "@expo/vector-icons/Ionicons";

export type ReportTypeId =
  | "autorites"
  | "secours"
  | "obstacle_nav"
  | "animal_marin"
  | "pollution"
  | "meteo"
  | "autre";

export type ReportExtra = "health" | "roche_variant" | "animal_species" | "pollution_level" | "comment_required";

export interface DriftWeights {
  /** Wind weight 1..10 (10 = drift dominated by wind). */
  V: number;
  /** Current weight 1..10 (10 = drift dominated by sea current). */
  C: number;
}

export interface ReportSubtypeDef {
  id: string;
  label: string;
  description?: string;
  /** null = fixed item, no drift cone (e.g. an unmapped rock). */
  drift: DriftWeights | null;
  /** Optional TTL override in minutes (defaults to parent type's TTL). */
  ttl_minutes?: number;
  /** Extra contextual fields the create-form must collect for this subtype. */
  extras?: ReportExtra[];
}

export interface ReportTypeDef {
  id: ReportTypeId;
  label: string;
  short: string;
  color: string;
  icon: keyof typeof Ionicons.glyphMap;
  description: string;
  /** Default report lifetime in minutes when no subtype overrides it. */
  default_ttl_minutes: number;
  subtypes: ReportSubtypeDef[];
}

// Health states reused across animal subtypes.
export const ANIMAL_HEALTH_STATES = [
  { id: "alive_healthy", label: "Vivant en bonne santé apparente" },
  { id: "alive_injured", label: "Vivant mais blessé ou malade" },
  { id: "dead_unmarked", label: "Mort sans traces de blessure apparente" },
  { id: "dead_injured", label: "Mort avec traces de blessures" },
  { id: "dead_pollution", label: "Mort avec traces de pollution hydrocarbure" },
] as const;

export const INJURY_TYPES = [
  { id: "boat_propeller", label: "Hélice de bateau" },
  { id: "fishing_gear", label: "Engin de pêche" },
  { id: "natural_predator", label: "Prédateur marin naturel" },
] as const;

// Main European marine mammals (non-exhaustive, ordered by frequency in
// French Atlantic + Channel waters).
export const MARINE_MAMMALS = [
  { id: "common_dolphin", label: "Dauphin commun" },
  { id: "bottlenose_dolphin", label: "Grand dauphin (Tursiops)" },
  { id: "white_beaked_dolphin", label: "Dauphin à bec blanc" },
  { id: "striped_dolphin", label: "Dauphin bleu et blanc" },
  { id: "risso_dolphin", label: "Dauphin de Risso" },
  { id: "harbor_porpoise", label: "Marsouin commun" },
  { id: "harbor_seal", label: "Phoque veau-marin" },
  { id: "grey_seal", label: "Phoque gris" },
  { id: "minke_whale", label: "Petit rorqual (baleine de Minke)" },
  { id: "fin_whale", label: "Rorqual commun" },
  { id: "sperm_whale", label: "Cachalot" },
  { id: "pilot_whale", label: "Globicéphale noir" },
  { id: "orca", label: "Orque" },
  { id: "other", label: "Autre / inconnu" },
] as const;

// Rock variants (no drift — always fixed).
export const ROCHE_VARIANTS = [
  { id: "couvrante_decouvrante", label: "Couvrante et découvrante" },
  { id: "toujours_couvrante", label: "Toujours couvrante" },
  { id: "toujours_decouvrante", label: "Toujours découvrante" },
] as const;

export const REPORT_TYPES: ReportTypeDef[] = [
  {
    id: "autorites",
    label: "Autorités maritimes",
    short: "Autorités",
    color: "#48CAE4",
    icon: "shield-checkmark",
    description: "Affaires Maritimes, Gendarmerie Maritime, Police de l'Environnement, Douanes…",
    default_ttl_minutes: 60,
    subtypes: [
      { id: "gendarmerie_maritime", label: "Gendarmerie Maritime", drift: null },
      { id: "affaires_maritimes", label: "Affaires Maritimes", drift: null },
      { id: "police_env", label: "Police de l'Environnement", drift: null },
      { id: "douanes", label: "Douanes maritimes", drift: null },
      { id: "autre_autorite", label: "Autre autorité", drift: null },
    ],
  },
  {
    id: "secours",
    label: "Secours en mer",
    short: "Secours",
    color: "#FF6B6B",
    icon: "medkit",
    description: "SNSM, Pompiers — moyens de sauvetage en mer.",
    default_ttl_minutes: 60,
    subtypes: [
      { id: "snsm", label: "SNSM (Société Nationale de Sauvetage en Mer)", drift: null },
      { id: "pompiers", label: "Pompiers maritimes", drift: null },
    ],
  },
  {
    id: "obstacle_nav",
    label: "Obstacle à la navigation",
    short: "Obstacle",
    color: "#F4A261",
    icon: "warning",
    description: "Roches, OFNI, bouées de pêche, conteneurs, bois flottants…",
    default_ttl_minutes: 60,
    subtypes: [
      {
        id: "roche",
        label: "Roche non répertoriée",
        description: "Toujours fixe — pas de dérive estimée.",
        drift: null,
        extras: ["roche_variant"],
      },
      {
        id: "ofni",
        label: "OFNI",
        description: "Objet Flottant Non Identifié.",
        drift: { V: 5, C: 5 },
      },
      {
        id: "bouee_peche",
        label: "Bouée ou matériel de pêche avec cordage",
        drift: { V: 8, C: 2 },
      },
      {
        id: "conteneur",
        label: "Conteneur partiellement immergé",
        drift: { V: 1, C: 9 },
      },
      {
        id: "bois_flottant",
        label: "Bois flottant (tronc, palette, branche)",
        drift: { V: 7, C: 3 },
      },
      // 24/07/2026 (demande armateur) — nouveaux obstacles DÉRIVANTS.
      {
        id: "embarcation_derive",
        label: "Embarcation à la dérive",
        drift: { V: 6, C: 4 },
      },
      {
        id: "nappe_sargasses",
        label: "Nappe de sargasses",
        drift: { V: 3, C: 7 },
      },
    ],
  },
  {
    id: "animal_marin",
    label: "Animal marin",
    short: "Animal",
    color: "#2A9D8F",
    icon: "fish",
    description: "Mammifère, oiseau ou autre animal — vivant, blessé ou mort.",
    default_ttl_minutes: 360, // 6h per spec
    subtypes: [
      {
        id: "mammifere",
        label: "Mammifère marin",
        drift: { V: 6, C: 4 },
        extras: ["animal_species", "health"],
      },
      {
        id: "oiseau",
        label: "Oiseau marin",
        drift: { V: 8, C: 2 },
        extras: ["health"],
      },
      {
        id: "autre_animal",
        label: "Autre animal",
        drift: { V: 5, C: 5 },
        extras: ["health"],
      },
    ],
  },
  {
    id: "pollution",
    label: "Pollution",
    short: "Pollution",
    color: "#9D4CDD",
    icon: "water",
    description: "Hydrocarbures, déchets, micro-plastiques visibles…",
    default_ttl_minutes: 360, // overridden by subtype
    subtypes: [
      {
        id: "pollution_cote",
        label: "Pollution à la côte",
        drift: { V: 4, C: 6 },
        ttl_minutes: 1440, // 24h per spec
      },
      {
        id: "pollution_locale",
        label: "Pollution locale",
        drift: { V: 5, C: 5 },
        ttl_minutes: 360, // 6h per spec
      },
      {
        id: "pollution_importante",
        label: "Pollution importante",
        drift: { V: 4, C: 6 },
        ttl_minutes: 720, // 12h per spec
      },
    ],
  },
  // 24/07/2026 (demande armateur) — PHÉNOMÈNES MÉTÉO, tous NON dérivants.
  {
    id: "meteo",
    label: "Phénomène météo",
    short: "Météo",
    color: "#5C7CFA",
    icon: "thunderstorm",
    description: "Orage proche, trombe marine, brume de mer…",
    default_ttl_minutes: 120,
    subtypes: [
      { id: "orage_proche", label: "Orage proche", drift: null },
      { id: "trombe_marine", label: "Trombe marine", drift: null },
      { id: "brume_mer", label: "Brume de mer / brouillard", drift: null },
    ],
  },
  {
    id: "autre",
    label: "Autre type de signalement",
    short: "Autre",
    color: "#6C757D",
    icon: "ellipsis-horizontal-circle",
    description: "Décrivez le phénomène (20 à 150 caractères).",
    default_ttl_minutes: 60,
    subtypes: [
      {
        id: "autre_libre",
        label: "Description libre",
        drift: null,
        extras: ["comment_required"],
      },
    ],
  },
];

export const TYPE_BY_ID: Record<ReportTypeId, ReportTypeDef> = REPORT_TYPES.reduce(
  (acc, t) => {
    acc[t.id] = t;
    return acc;
  },
  {} as Record<ReportTypeId, ReportTypeDef>,
);

export function getSubtype(typeId: ReportTypeId, subtypeId: string): ReportSubtypeDef | undefined {
  return TYPE_BY_ID[typeId]?.subtypes.find((s) => s.id === subtypeId);
}

export function effectiveTTLMinutes(typeId: ReportTypeId, subtypeId?: string | null): number {
  const t = TYPE_BY_ID[typeId];
  if (!t) return 60;
  if (subtypeId) {
    const s = t.subtypes.find((x) => x.id === subtypeId);
    if (s?.ttl_minutes) return s.ttl_minutes;
  }
  return t.default_ttl_minutes;
}
