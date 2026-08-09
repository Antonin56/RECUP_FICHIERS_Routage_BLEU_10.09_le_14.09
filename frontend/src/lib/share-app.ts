// SignalMar — sharing helpers.
// Centralises every share message so the wording stays consistent across the
// app (Profil → Partager l'app, Détail signalement → Partager).
//
// The Play Store / App Store links are commented out until publication. When
// the apps ship to the stores, just flip APP_STORE_LINK / PLAY_STORE_LINK
// from `null` to the live URLs and the share captions pick them up.

export const APP_NAME = "SignalMar";
export const APP_TAGLINE = "L'appli collaborative des marins.";
export const APP_UNIVERSAL_LINK_BASE = "https://signalmar.app";

// TODO(release) — uncomment + fill once the apps are live in the stores.
// export const PLAY_STORE_LINK = "https://play.google.com/store/apps/details?id=app.signalmar";
// export const APP_STORE_LINK = "https://apps.apple.com/app/signalmar/id000000000";
export const PLAY_STORE_LINK: string | null = null;
export const APP_STORE_LINK: string | null = null;

/**
 * Phase B — Build a universal-link that carries the referrer's code so
 * the parrainage can be attributed at signup even when the invited user
 * clicks the link before the app is installed.
 *
 * TODO(release) — quand le domaine signalmar.app sera actif, repasser sur
 * `https://signalmar.app/i/<code>`. En attendant, le lien pointe vers la
 * landing /api/join de l'environnement courant (fonctionnelle : détection
 * OS, code parrain affiché, carte live) pour que les SMS d'invitation
 * mènent quelque part dès aujourd'hui.
 */
const ENV_BASE = (process.env.EXPO_PUBLIC_BACKEND_URL || "").replace(/\/+$/, "");

export function signalMarInviteUrl(refCode?: string | null): string {
  if (ENV_BASE) {
    return refCode
      ? `${ENV_BASE}/api/join?ref=${encodeURIComponent(refCode)}`
      : `${ENV_BASE}/api/join`;
  }
  const base = `${APP_UNIVERSAL_LINK_BASE}/i`;
  return refCode ? `${base}/${encodeURIComponent(refCode)}` : APP_UNIVERSAL_LINK_BASE;
}

/**
 * Page web publique d'un signalement (12/07/2026) — `/s/[CODE]`.
 * TODO(release) — deviendra `https://signalmar.app/s/<code>` quand le
 * domaine sera actif ; en attendant, pointe vers l'environnement courant.
 */
export function signalMarReportUrl(shortId?: string | null): string {
  const base = ENV_BASE || APP_UNIVERSAL_LINK_BASE;
  return shortId ? `${base}/s/${encodeURIComponent(shortId)}` : base;
}

function storeFooter(): string {
  // While the stores aren't live yet we still mention them so people know
  // SignalMar will be released — they just don't get an active link.
  if (PLAY_STORE_LINK || APP_STORE_LINK) {
    const parts: string[] = [];
    if (PLAY_STORE_LINK) parts.push(`Android : ${PLAY_STORE_LINK}`);
    if (APP_STORE_LINK) parts.push(`iOS : ${APP_STORE_LINK}`);
    return `\n\n${parts.join("\n")}`;
  }
  return "\n\nBientôt disponible sur l'App Store et Google Play.";
}

export function shareAppMessage(refCode?: string | null): string {
  const link = signalMarInviteUrl(refCode);
  return `${APP_NAME} — ${APP_TAGLINE}\n` +
    "Repère, partage et confirme les obstacles, animaux et pollutions en mer, en temps réel.\n\n" +
    `Rejoins-moi : ${link}` +
    storeFooter();
}

export function shareReportMessage(args: {
  typeLabel: string;
  description?: string;
  coords?: string;
  refCode?: string | null;
}): string {
  const lines: string[] = [`${APP_NAME} — ${args.typeLabel}`];
  if (args.description) lines.push(args.description);
  if (args.coords) lines.push(`Position : ${args.coords}`);
  lines.push("");
  lines.push("Signalé via SignalMar, l'appli collaborative des marins.");
  lines.push(`Rejoins-moi : ${signalMarInviteUrl(args.refCode)}`);
  return lines.join("\n") + storeFooter();
}

/** SMS d'invitation à un GROUPE privé (mode groupe de /share-invite, 11/07). */
export function shareGroupMessage(args: {
  groupName: string;
  inviteCode: string;
  refCode?: string | null;
}): string {
  return (
    `🌊 Rejoins mon groupe privé SignalMar « ${args.groupName} » !\n` +
    `Code d'invitation : ${args.inviteCode}\n\n` +
    `Télécharge l'app et retrouve-nous : ${signalMarInviteUrl(args.refCode)}\n` +
    `Dans l'app : Groupes → Rejoindre avec un code.` +
    storeFooter()
  );
}
