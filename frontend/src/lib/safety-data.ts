// SignalMar — Données de sécurité maritime.
// Mirror de la "Division 240" (Arrêté du 11 mars 2008 modifié) — version
// officielle française de février 2024 fournie par l'utilisateur.
//
// CHAQUE catégorie de navigation possède sa propre liste de matériels
// obligatoires. La logique n'est PAS purement cumulative : certains items
// disparaissent ou apparaissent selon la catégorie (ex : les "3 feux rouges
// à main" ne sont plus obligatoires en hauturier où l'EPIRB devient
// obligatoire à la place). Chaque item porte donc la liste exacte des
// catégories où il est requis (`required_in`).
//
// Les textes des notes (footnotes) sont strictement VERBATIM du PDF.
// Source : "equipement_securite_navires_plaisance_022024.pdf" (Affmar 2024).

export type CategoryId = "cotier" | "semi_hauturier" | "hauturier" | "basique";

export interface SafetyCategory {
  id: CategoryId;
  label: string;
  range: string;       // distance verbatim (avec * pour la note "Abri")
  icon: string;        // Ionicons name
  color: string;
}

// Affichage : Côtier en premier (le plus répandu), Basique en dernier.
export const SAFETY_CATEGORIES: SafetyCategory[] = [
  { id: "cotier",         label: "Côtier",         range: "Jusqu'à 6 milles d'un abri*",   icon: "compass-outline", color: "#2A9D8F" },
  { id: "semi_hauturier", label: "Semi-hauturier", range: "Entre 6 et 60 milles d'un abri*", icon: "navigate-outline", color: "#E9C46A" },
  { id: "hauturier",      label: "Hauturier",      range: "Au-delà de 60 milles d'un abri*", icon: "earth-outline",   color: "#E76F51" },
  { id: "basique",        label: "Basique",        range: "Jusqu'à 2 milles d'un abri*",   icon: "boat-outline",    color: "#48CAE4" },
];

// ─── Notes de bas de page (textes VERBATIM du PDF Division 240) ───────────
export type FootnoteId =
  | "abri"
  | "eif"
  | "lumineux"
  | "coupe_circuit"
  | "fusees"
  | "compas"
  | "harnais"
  | "vhf";

export interface SafetyFootnote {
  id: FootnoteId;
  title: string;
  body: string;
}

export const SAFETY_FOOTNOTES: Record<FootnoteId, SafetyFootnote> = {
  abri: {
    id: "abri",
    title: "Abri",
    body:
      "Endroit de la côte où tout engin, embarcation ou navire et son équipage peuvent se mettre en sécurité en mouillant, atterrissant ou accostant et en repartir sans assistance. Cette notion tient compte des conditions météorologiques du moment ainsi que des caractéristiques de l'engin, de l'embarcation ou du navire.\n\nCas particulier : les annexes, embarcations utilisées à des fins de servitude à partir d'un navire porteur, ne peuvent s'éloigner à plus de 300 mètres d'un abri côtier ou du navire porteur ; celui-ci étant considéré comme un abri. Néanmoins, à plus de 300 mètres de la côte, il faut embarquer un moyen de repérage lumineux ainsi qu'un équipement individuel de flottabilité par personne.",
  },
  eif: {
    id: "eif",
    title: "Équipement individuel de flottabilité (EIF)",
    body:
      "La norme doit être NF-EN 12402 avec 3 niveaux de performance : 50, 100, 150. L'équipement doit être adapté à la morphologie de chacun et ses performances doivent répondre aux caractéristiques suivantes :\n\n• performance 50 au moins (aide à la flottabilité) pour une navigation jusqu'à 2 milles d'un abri ;\n• performance 100 au moins (gilet de sauvetage) pour une navigation jusqu'à 6 milles d'un abri (emport de gilet de 100 ou port de gilet de 50) ;\n• performance 150 au moins (gilet de sauvetage) pour une navigation toutes zones ;\n• les enfants de 30 kg maximum doivent porter un EIF de performance 100 au moins en permanence quelle que soit la distance d'éloignement d'un abri.\n\nNouveau : un guide pour le choix de l'EIF avec le niveau de flottabilité minimal en fonction du poids des utilisateurs. Ce guide est en annexe 240-A4 de la division 240.\n\nCes équipements sont approuvés ou marqués CE.",
  },
  lumineux: {
    id: "lumineux",
    title: "Dispositif lumineux",
    body:
      "Pour être secouru il faut être vu.\n\nUne lampe torche étanche embarquée. Sinon un moyen lumineux individuel (type lampe Flash ou cyalume) d'une autonomie minimale de 6 heures et assujetti à chaque équipement individuel de flottabilité.",
  },
  coupe_circuit: {
    id: "coupe_circuit",
    title: "Coupe-circuit (y compris électronique)",
    body:
      "Obligation du port d'un coupe-circuit relié au poignet ou à la jambe ou à l'EIF porté dès l'allumage du moteur. Il ne peut être modifié (rallongé ou déplacé).\n\nPour les coupes-circuit électroniques, un passager doit rester au poste de pilotage afin d'éviter toute manipulation de la manette des gaz. Un second coupe-circuit filaire est accessible à bord et son endroit est identifié par tous les passagers.\n\n(Plus d'informations sur la Division 240 : paragraphe 7 de l'article 240-2.01).",
  },
  fusees: {
    id: "fusees",
    title: "Fusées à parachute et feux rouges à main",
    body:
      "Les fusées périmées peuvent être rendues au point de vente lors de l'achat de nouvelles.\n\nNe pas les jeter, ne pas les stocker, ni les utiliser comme feux d'artifice qui déclencheraient des secours en mer.",
  },
  compas: {
    id: "compas",
    title: "Compas magnétique",
    body:
      "Il doit être étanche, fixé temporairement ou en permanence au navire, et visible depuis le poste de conduite. Il doit être de classe A ou B, être compensé et disposer d'un éclairage. Il doit afficher le cap au poste de barre principal du navire, il doit être indépendant de toute source d'énergie, à l'exception de l'éclairage.\n\nLes compas magnétiques qui répondent aux exigences de la norme ISO 25862:2019 ou ISO 14227:2001 n'ont pas à suivre ces dispositions.",
  },
  harnais: {
    id: "harnais",
    title: "Harnais et longe",
    body:
      "(Par navire pour les non voiliers, par personne sur les voiliers.)\n\nIls doivent s'attacher à une ligne de vie ou un point d'accrochage sur le navire. Ces points n'ont pas besoin d'être exclusivement dédiés à cet usage.",
  },
  vhf: {
    id: "vhf",
    title: "VHF",
    body:
      "Une VHF fixe est obligatoire pour une navigation semi-hauturière. Les 3 fusées à parachute et les 2 fumigènes ne sont plus obligatoires.\n\nTout navire équipé d'une radio VHF (fixe ou portable) doit rester à l'écoute du canal 16 lorsqu'il est en mer, en complément de la veille visuelle et auditive permanente.",
  },
};

// ─── Items obligatoires — Division 240 (textes VERBATIM, ordre du tableau) ─
export interface SafetyItem {
  id: string;
  label: string;
  /** Notes liées à cet item (icône ? à côté). */
  footnotes?: FootnoteId[];
  /** Catégories où l'item est requis (case cochée dans le tableau du PDF). */
  required_in: CategoryId[];
}

export const SAFETY_ITEMS: SafetyItem[] = [
  {
    id: "eif",
    label: "Équipement individuel de flottabilité",
    footnotes: ["eif"],
    required_in: ["basique", "cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "lumineux",
    label: "Dispositif lumineux",
    footnotes: ["lumineux"],
    required_in: ["basique", "cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "coupe_circuit",
    label: "Coupe-circuit (pour moteur hors-bord avec commande barre ou déporté et VNM)",
    footnotes: ["coupe_circuit"],
    required_in: ["basique", "cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "lutte_incendie",
    label: "Moyens mobiles de lutte contre l'incendie (indiqués dans le manuel du propriétaire)",
    required_in: ["basique", "cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "assechement",
    label: "Dispositif d'assèchement manuel",
    required_in: ["basique", "cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "remorquage",
    label: "Dispositif de remorquage",
    required_in: ["basique", "cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "ligne_mouillage",
    label: "Ligne de mouillage (si masse lège ≥ 250 kg)",
    required_in: ["basique", "cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "annuaire_marees",
    label: "Annuaire des marées",
    required_in: ["cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "pavillon",
    label: "Pavillon national (hors eaux territoriales)",
    required_in: ["cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "fer_a_cheval",
    label:
      "Dispositif de repérage et d'assistance pour personne à la mer de type bouée fer à cheval ou bouée couronne",
    required_in: ["cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "feux_rouges",
    label: "3 feux rouges à main",
    footnotes: ["fusees"],
    required_in: ["cotier", "semi_hauturier"],
  },
  {
    id: "compas",
    label: "Compas magnétique",
    footnotes: ["compas"],
    required_in: ["cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "cartes_marines",
    label: "Cartes marines officielles (voir la fiche « Les documents nautiques »)",
    required_in: ["cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "ripam",
    label:
      "Règlement international pour prévenir les abordages en mer (RIPAM)",
    required_in: ["cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "balisage",
    label: "Description du système de balisage",
    required_in: ["cotier", "semi_hauturier", "hauturier"],
  },
  {
    id: "radeau",
    label: "Radeau de survie",
    required_in: ["hauturier"],
  },
  {
    id: "materiel_point",
    label: "Matériel pour faire le point",
    required_in: ["semi_hauturier", "hauturier"],
  },
  {
    id: "livre_feux",
    label: "Livre des feux tenu à jour (voir fiche « Les documents nautiques »)",
    required_in: ["semi_hauturier", "hauturier"],
  },
  {
    id: "journal_bord",
    label: "Journal de bord",
    required_in: ["semi_hauturier", "hauturier"],
  },
  {
    id: "reception_meteo",
    label: "Dispositif de réception des bulletins météorologiques",
    required_in: ["semi_hauturier", "hauturier"],
  },
  {
    id: "harnais_navire",
    label: "Harnais et longe par navire pour les non voiliers",
    footnotes: ["harnais"],
    required_in: ["semi_hauturier", "hauturier"],
  },
  {
    id: "harnais_perso",
    label: "Harnais et longe par personne embarquée pour les voiliers",
    footnotes: ["harnais"],
    required_in: ["semi_hauturier", "hauturier"],
  },
  {
    id: "trousse_secours",
    label: "Trousse de secours conforme à l'article 240-2.16",
    required_in: ["semi_hauturier", "hauturier"],
  },
  {
    id: "lumineux_nuit",
    label: "Dispositif lumineux pour la recherche et le repérage de nuit",
    required_in: ["semi_hauturier", "hauturier"],
  },
  {
    id: "epirb",
    label: "Radiobalise de localisation des sinistres (EPIRB)",
    required_in: ["hauturier"],
  },
  {
    id: "vhf_fixe",
    label: "VHF fixe",
    footnotes: ["vhf"],
    required_in: ["semi_hauturier", "hauturier"],
  },
  {
    id: "vhf_portative",
    label: "VHF portative",
    footnotes: ["vhf"],
    required_in: ["hauturier"],
  },
];

/** Retourne la liste des matériels obligatoires pour une catégorie. */
export function materialsFor(cat: CategoryId): SafetyItem[] {
  return SAFETY_ITEMS.filter((it) => it.required_in.includes(cat));
}

// ─── Bouées IALA Région A (inchangé — utilisé par l'onglet « Bouées ») ────
export interface BuoyDef {
  id: string;
  family: "cardinale" | "laterale" | "speciale" | "danger_isole" | "eaux_saines" | "danger_nouveau" | "atterrissage";
  name: string;
  description: string;
  light: string;
  topmark?: string;
  bands: string[];
  shape?: "pillar" | "spar" | "spherical" | "conical" | "can";
}

export const BUOYS: BuoyDef[] = [
  { id: "card_n", family: "cardinale", name: "Cardinale Nord", description: "Passer au NORD de la bouée — eaux saines au nord.", light: "VQ ou Q (continu)", topmark: "▲▲", bands: ["#111", "#FFD22E"] },
  { id: "card_e", family: "cardinale", name: "Cardinale Est",  description: "Passer à l'EST — eaux saines à l'est.", light: "VQ(3) 5s ou Q(3) 10s", topmark: "▲▼", bands: ["#111", "#FFD22E", "#111"] },
  { id: "card_s", family: "cardinale", name: "Cardinale Sud",  description: "Passer au SUD — eaux saines au sud.", light: "VQ(6)+LFl 10s ou Q(6)+LFl 15s", topmark: "▼▼", bands: ["#FFD22E", "#111"] },
  { id: "card_w", family: "cardinale", name: "Cardinale Ouest", description: "Passer à l'OUEST — eaux saines à l'ouest.", light: "VQ(9) 10s ou Q(9) 15s", topmark: "▼▲", bands: ["#FFD22E", "#111", "#FFD22E"] },
  { id: "lat_p", family: "laterale", name: "Latérale Bâbord", description: "Laisser à BÂBORD (à gauche) en entrant au port.", light: "Rouge — toutes cadences sauf composite", topmark: "■", bands: ["#D62828"], shape: "can" },
  { id: "lat_s", family: "laterale", name: "Latérale Tribord", description: "Laisser à TRIBORD (à droite) en entrant au port.", light: "Vert — toutes cadences sauf composite", topmark: "▲", bands: ["#2A9D8F"], shape: "conical" },
  { id: "lat_pref_p", family: "laterale", name: "Tribord préféré", description: "Chenal préféré à TRIBORD (passer à gauche).", light: "Rouge Fl(2+1) 6s", topmark: "■", bands: ["#D62828", "#2A9D8F", "#D62828"] },
  { id: "lat_pref_s", family: "laterale", name: "Bâbord préféré", description: "Chenal préféré à BÂBORD (passer à droite).", light: "Vert Fl(2+1) 6s", topmark: "▲", bands: ["#2A9D8F", "#D62828", "#2A9D8F"] },
  { id: "isolated", family: "danger_isole", name: "Danger isolé", description: "Danger ponctuel — passer à distance.", light: "Fl(2) 5s blanc", topmark: "● ●", bands: ["#111", "#D62828", "#111"] },
  { id: "safe_water", family: "eaux_saines", name: "Eaux saines", description: "Pas de danger — milieu de chenal, atterrissage.", light: "Iso, Occ, LFl 10s ou Morse A blanc", topmark: "●", bands: ["#D62828", "#FFFFFF", "#D62828", "#FFFFFF"] },
  { id: "special", family: "speciale", name: "Marque spéciale", description: "Zones particulières (mouillage, câbles, militaire, etc.).", light: "Jaune — toutes cadences sauf celles des autres marques", topmark: "✕", bands: ["#FFD22E"] },
  { id: "emerg", family: "danger_nouveau", name: "Danger nouveau", description: "Épave ou danger non encore reporté — peut être doublé.", light: "Alternance bleu/jaune Bu(1)+Y(1) ou Alt B-Y 3s", bands: ["#0A66C2", "#FFD22E", "#0A66C2", "#FFD22E"] },
];

// ─── Règles essentielles (inchangé) ──────────────────────────────────────
export interface SafetyRule {
  id: string;
  title: string;
  body: string;
  icon: string;
}

export const SAFETY_RULES: SafetyRule[] = [
  { id: "veille_16", title: "Veille VHF Canal 16", body: "Le canal 16 est la fréquence internationale d'appel et de détresse. Gardez une veille permanente en navigation.", icon: "radio-outline" },
  { id: "voile_moteur", title: "Voile prioritaire sur moteur", body: "Un voilier sans moteur en marche est prioritaire sur un navire à moteur — sauf rattrapage ou voie maintenue d'un navire de commerce.", icon: "boat-outline" },
  { id: "tribord", title: "Priorité tribord (route)", body: "Tout navire arrivant sur votre tribord est prioritaire. Vous devez manœuvrer pour le laisser passer.", icon: "arrow-forward-circle-outline" },
  { id: "depasse", title: "Dépassement", body: "Le navire qui dépasse manœuvre seul. Ne jamais couper la route d'un navire en train de dépasser.", icon: "swap-horizontal-outline" },
  { id: "feux", title: "Feux de nuit", body: "Feu blanc poupe + feu rouge bâbord + feu vert tribord. Reconnaître les cap d'un navire la nuit grâce à ses feux.", icon: "moon-outline" },
  { id: "vitesse", title: "Vitesse adaptée", body: "Adaptez votre vitesse à la visibilité, à la densité du trafic et aux conditions météo. À l'approche des ports : ≤ 5 nœuds.", icon: "speedometer-outline" },
  { id: "plan_nav", title: "Plan de navigation", body: "Toujours prévenir un proche de votre itinéraire, équipage et heure de retour. En cas d'absence prolongée, il pourra alerter le CROSS.", icon: "document-text-outline" },
  { id: "meteo", title: "Bulletin météo", body: "Consultez le bulletin de la zone (BMS) avant chaque sortie. France : VHF canal 79 ou 80 + Météo France Marine.", icon: "cloudy-outline" },
  { id: "detresse", title: "Procédure de détresse", body: "MAYDAY MAYDAY MAYDAY · « Ici [nom du bateau] × 3 » · Position GPS · Nature de la détresse · Nombre de personnes · Type d'assistance demandée.", icon: "warning-outline" },
  { id: "1616", title: "Numéro d'urgence en mer", body: "Composez le 196 (CROSS) ou le 1616 depuis un téléphone à terre/en mer. L'app dispose d'un bouton SOS dans l'onglet Détresse.", icon: "call-outline" },
];
