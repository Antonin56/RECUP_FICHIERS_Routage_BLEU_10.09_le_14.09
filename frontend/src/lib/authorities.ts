// Sub-types + activities for autorites & secours (both share the same
// runtime UI patterns: subtype tiles + activity tiles + optional cap/vitesse).

export type AuthoritySubtype = string;
export type AuthorityActivity = "navigation" | "control" | "stationary" | "operation";

export const AUTHORITY_SUBTYPES: { id: AuthoritySubtype; label: string }[] = [
  { id: "affaires_maritimes", label: "Affaires Maritimes" },
  { id: "gendarmerie_maritime", label: "Gendarmerie Maritime" },
  { id: "police_env", label: "Police de l'Environnement" },
  { id: "douanes", label: "Douanes maritimes" },
  { id: "autre_autorite", label: "Autre autorité" },
];

export const SECOURS_SUBTYPES: { id: AuthoritySubtype; label: string }[] = [
  { id: "snsm", label: "SNSM" },
  { id: "pompiers", label: "Pompiers" },
];

type Icon = keyof typeof import("@expo/vector-icons/Ionicons").default.glyphMap;

export const AUTHORITY_ACTIVITIES: {
  id: AuthorityActivity;
  label: string;
  icon: Icon;
}[] = [
  { id: "navigation", label: "En navigation", icon: "navigate" },
  { id: "control", label: "En contrôle", icon: "search" },
  { id: "stationary", label: "Stationnaire", icon: "stop-circle" },
];

// Secours activities (per cahier des charges 28/06): nav / opération / stationnaire.
export const SECOURS_ACTIVITIES: {
  id: AuthorityActivity;
  label: string;
  icon: Icon;
}[] = [
  { id: "navigation", label: "En navigation", icon: "navigate" },
  { id: "operation", label: "En opération", icon: "medkit" },
  { id: "stationary", label: "Stationnaire", icon: "stop-circle" },
];

export const ALL_SUBTYPES = [...AUTHORITY_SUBTYPES, ...SECOURS_SUBTYPES];
export const ALL_ACTIVITIES = [...AUTHORITY_ACTIVITIES, ...SECOURS_ACTIVITIES];

export const SUBTYPE_LABEL: Record<string, string> = ALL_SUBTYPES.reduce(
  (acc, s) => {
    acc[s.id] = s.label;
    return acc;
  },
  {} as Record<string, string>,
);

export const ACTIVITY_LABEL: Record<string, string> = ALL_ACTIVITIES.reduce(
  (acc, a) => {
    acc[a.id] = a.label;
    return acc;
  },
  {} as Record<string, string>,
);
