// SignalMar — Construction des messages d'alerte vocale.
//
// Selon le TYPE de signalement (type + sous-type + health) et la VITESSE du
// barreur, on produit un message verbalisé prêt à être envoyé au TTS.
//
// Règles (cahier des charges) :
//   • Mammifères marins MORTS ou BLESSÉS, et obstacles à la navigation
//     → message MODULÉ par la vitesse.
//   • Autorités → message FIXE (toute vitesse).
//   • Aucun message pour : secours, pollution (côte/locale), animaux
//     non-mammifères ou mammifères vivants en bonne santé, "autre".

export interface ReportAlertInput {
  type: string;        // type-level id ("autorites" | "obstacle_nav" | "animal_marin" | …)
  subtype?: string;    // subtype id ("gendarmerie_maritime", "ofni", "mammifere", …)
  health?: string;     // animal_marin : alive_healthy | alive_injured | dead_*
}

const KNOT_MS = 0.5144;

interface AlertSubject {
  text: string;        // mot/expression à insérer dans la phrase
  accord: "signalé" | "signalée" | "signalés" | "signalées";
}

/** Libellé verbal pour les sous-types d'AUTORITÉ. */
const AUTHORITY_SUBJECTS: Record<string, AlertSubject> = {
  gendarmerie_maritime: { text: "gendarmerie maritime",          accord: "signalée" },
  affaires_maritimes:   { text: "affaires maritimes",            accord: "signalées" },
  police_env:           { text: "police de l'environnement",     accord: "signalée" },
  douanes:              { text: "douanes maritimes",             accord: "signalées" },
  autre_autorite:       { text: "autorité maritime",             accord: "signalée" },
};

/** Libellé verbal pour les sous-types d'OBSTACLE. */
const OBSTACLE_SUBJECTS: Record<string, AlertSubject> = {
  roche:         { text: "roche non répertoriée",                accord: "signalée" },
  ofni:          { text: "objet flottant non identifié",         accord: "signalé" },
  bouee_peche:   { text: "bouée ou matériel de pêche",           accord: "signalé" },
  conteneur:     { text: "conteneur partiellement immergé",      accord: "signalé" },
  bois_flottant: { text: "bois flottant",                        accord: "signalé" },
};

/** Libellé verbal pour les POLLUTIONS avec alerte (13/07/2026, demande user).
 *  « Pollution à la côte » reste volontairement silencieuse. */
const POLLUTION_SUBJECTS: Record<string, AlertSubject> = {
  pollution_locale:     { text: "pollution locale",     accord: "signalée" },
  pollution_importante: { text: "pollution importante", accord: "signalée" },
};

/** Préfixe selon le tier de vitesse (en m/s). */
function speedPrefix(speedMs: number | null | undefined): "calm" | "vigilant" | "urgent" {
  const sp = (typeof speedMs === "number" && speedMs >= 0) ? speedMs : 0;
  const kn = sp / KNOT_MS;
  if (kn > 10) return "urgent";
  if (kn >= 5) return "vigilant";
  return "calm";
}

/** Construit le message vocal final — null si pas d'alerte. */
export function buildAlertText(
  input: ReportAlertInput,
  speedMs: number | null | undefined,
): string | null {
  // ── Autorités → message fixe quelle que soit la vitesse ──
  if (input.type === "autorites") {
    const subj = AUTHORITY_SUBJECTS[input.subtype ?? "autre_autorite"]
      ?? AUTHORITY_SUBJECTS.autre_autorite;
    return `Attention, ${subj.text} ${subj.accord} dans votre périmètre d'alerte.`;
  }

  // ── Obstacles à la navigation → message modulé ──
  if (input.type === "obstacle_nav") {
    const subj = OBSTACLE_SUBJECTS[input.subtype ?? ""] ?? { text: "obstacle à la navigation", accord: "signalé" as const };
    return modulated(subj, speedMs);
  }

  // ── Mammifères marins → alerte quelle que soit la santé apparente ──
  // Phase K.14 — Correction du bug remonté par le terrain : un mammifère
  // marin même « vivant, en bonne santé » représente un risque de
  // collision + un enjeu de bien-être animal. On alerte donc pour tous
  // les états (vivant / blessé / mort), on ne module que le libellé.
  if (input.type === "animal_marin" && input.subtype === "mammifere") {
    const hs = healthState(input.health);
    const text = hs === "dead"
      ? "mammifère marin mort"
      : hs === "injured"
        ? "mammifère marin blessé"
        : "mammifère marin";
    return modulated({ text, accord: "signalé" }, speedMs);
  }

  // ── Oiseaux marins & autres animaux : alerte uniquement si blessé/mort ──
  if (input.type === "animal_marin" && (input.subtype === "oiseau" || input.subtype === "autre_animal")) {
    const hs = healthState(input.health);
    if (hs === "other") return null;
    const base = input.subtype === "oiseau" ? "oiseau marin" : "animal marin";
    const text = hs === "dead" ? `${base} mort` : `${base} blessé`;
    return modulated({ text, accord: "signalé" }, speedMs);
  }

  // ── Pollution locale & importante (13/07/2026) → message modulé ──
  if (input.type === "pollution" && input.subtype && POLLUTION_SUBJECTS[input.subtype]) {
    return modulated(POLLUTION_SUBJECTS[input.subtype], speedMs);
  }

  // ── Pas d'alerte pour : secours, pollution à la côte, "autre", etc.
  return null;
}

// Normalisation robuste de l'état de santé (audit 12/07/2026) : le formulaire
// émet alive_healthy | alive_injured | dead_* mais on accepte aussi les
// synonymes FR/EN (blesse, mort…) venant d'anciens documents ou d'imports.
function healthState(h: string | undefined): "dead" | "injured" | "other" {
  const v = (h ?? "").toLowerCase();
  if (v.startsWith("dead") || v === "mort" || v === "morte") return "dead";
  if (v === "alive_injured" || v === "injured" || v === "blesse" || v === "bless\u00e9" || v === "blessee") return "injured";
  return "other";
}

function modulated(subj: AlertSubject, speedMs: number | null | undefined): string {
  const phrase = `${subj.text} ${subj.accord} dans votre périmètre d'alerte.`;
  switch (speedPrefix(speedMs)) {
    case "urgent":   return `Attention ! Soyez très vigilant : ${phrase}`;
    case "vigilant": return `Soyez vigilant, ${phrase}`;
    case "calm":     return `${capitalize(subj.text)} ${subj.accord} dans votre périmètre d'alerte.`;
  }
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Texte démo pour le bouton "Tester la voix". */
export function previewAlertText(): string {
  return "Attention ! Soyez très vigilant : mammifère marin blessé signalé dans votre périmètre d'alerte.";
}

/** 1 mille nautique en mètres. */
export const NM_IN_M = 1852;

/** Réglages par défaut — exportés pour le bouton "Restaurer". */
export const DEFAULT_VOICE_SETTINGS = {
  enabled: true,
  voice: "alloy" as "alloy" | "echo",
  vibrationEnabled: true,
  // Son d'alerte (14/07/2026, configurable depuis les Réglages) :
  //   "horn"  = corne de brume (défaut) · "sonar" = ping sonar.
  alertSound: "horn" as "horn" | "sonar",
  // Volume des alertes (0,2 → 1). 1 = MAXIMUM de ce que le téléphone peut
  // produire (défaut, demande user 13/07) — le plafond réel reste le volume
  // média réglé sur l'appareil. Ajustable depuis les Réglages.
  volume: 1.0,
  // Bascule AUTO Vigie ⇄ Navigation selon la vitesse du bateau
  // (≥ 3 km/h maintenu 5 s → Navigation ; < 3 km/h 5 s → Vigie).
  // Activée par défaut (11/07/2026).
  autoModeSwitch: true,
  // Zone de veille — UNE valeur par mode (fusion rayon notifications +
  // rayon d'alerte sonore, 10/07/2026) :
  //   • Vigie      : rayon du radar 360° (diamètre affiché = 2 × zone).
  //   • Navigation : longueur du cône devant le bateau.
  zoneVigieM: 2 * NM_IN_M,     // 2 NM = 3 704 m
  zoneNavM: 5 * NM_IN_M,       // 5 NM = 9 260 m
  // ── 17/07/2026 (v2 cône coloré) ── Distance de déclenchement d'alerte
  // sonore en mode NAVIGATION. Toujours ≤ zoneNavM (longueur visuelle du
  // cône). Séparation cône = « awareness zone » / alertDistance = « zone
  // critique » (change la couleur du cône à ROUGE + son). Défaut :
  //   • Nouveaux comptes → 60 % de la longueur du cône (bandeau orange
  //     visible d'emblée).
  //   • Comptes existants (migration) → EGAL à zoneNavM ⇒ ZÉRO régression
  //     sonore, l'orange n'existe pas tant que l'utilisateur ne baisse pas
  //     lui-même le curseur (voir voice-settings.ts).
  alertDistanceNavM: Math.round(5 * NM_IN_M * 0.6), // 60 % du cône par défaut
  // Bandeau one-shot expliquant la nouveauté « distance d'alerte séparée ».
  // Passé à true après affichage → jamais réaffiché.
  navAlertDistanceIntroSeen: false,
  // Types de signalement qui NE déclenchent PAS d'alerte sonore (liste
  // d'exclusion : tout nouveau type ajouté au catalogue est donc actif par
  // défaut, sans migration).
  mutedTypes: [] as string[],
  // Répétitions de l'alerte si l'utilisateur ne l'interrompt pas :
  // 0 à 2 relances espacées de repeatDelaySec, puis extinction automatique.
  // Total diffusé = 1 annonce + `repetitions` répétitions, puis SILENCE tant
  // qu'on reste dans le périmètre. Défaut 2 (13/07/2026 : plafond abaissé
  // 3 → 2 sur demande user).
  repetitions: 2,
  repeatDelaySec: 15,
};
export type VoiceSettings = typeof DEFAULT_VOICE_SETTINGS;
