/**
 * Phase 4.2b — Direct targeted invitation utilities.
 *
 * Central home for:
 *   1. The canonical French SMS / WhatsApp message template (locked with
 *      the user — see the group-invite discussion in the July session).
 *   2. `openInvitationChannels()` — best-effort auto-launch of the SMS
 *      composer and/or the WhatsApp chat, pre-filled with the message.
 *      iOS & Android forbid *silent* SMS from an app, so the final tap
 *      « Envoyer » stays in the user's hands, but everything else is
 *      automated : recipient phone is pre-selected, message is typed.
 *   3. `guessFirstName()` — extracts a friendly first name from the
 *      address-book label ("Jean Dupont" → "Jean", "Ancre 22" → "Ancre").
 *
 * The transport layer (SMS + WhatsApp) is intentionally decoupled from
 * the invite creation itself: even if the user cancels every messenger,
 * the `group_invitations` doc lives in Mongo and the invitee will see
 * the pending invitation at their next app launch.  This is the whole
 * point of the redesign — no more copy-pasting codes.
 */
import { Linking, Platform } from "react-native";
import * as SMS from "expo-sms";

import { signalMarInviteUrl } from "@/src/lib/share-app";

export interface InviteMessageContext {
  contactDisplayName: string;
  contactPhoneE164?: string;
  groupName: string;
  inviterPseudo: string;
  /** Phase B — referral code of the inviter, embedded in the deep-link
   *  so the parrainage bonus is attributed at signup. Optional : if
   *  omitted the message still works, just without attribution. */
  inviterReferralCode?: string | null;
}

export function guessFirstName(displayName: string): string {
  const clean = (displayName || "").trim();
  if (!clean) return "";
  // Prefer the first word if it looks like a Given Name (starts with a
  // letter). Otherwise fall back to the raw label.
  const first = clean.split(/\s+/)[0];
  return /^[A-Za-zÀ-ÖØ-öø-ÿ'-]{2,}$/.test(first) ? first : clean;
}

export function buildInvitationText(ctx: InviteMessageContext): string {
  const salut = guessFirstName(ctx.contactDisplayName) || "l'ami";
  const link = signalMarInviteUrl(ctx.inviterReferralCode);
  return (
    `Salut ${salut}, rejoins mon groupe privé SignalMar (${ctx.groupName}), ` +
    `on pourra y partager des infos, des positions et des messages privés ` +
    `juste entre nous.\n\n` +
    `Ouvre simplement SignalMar, tu seras directement dirigé vers ` +
    `l'invitation, et tu valides en cliquant sur Rejoindre, tu verras ça va ` +
    `être sympa.\n\n` +
    `Télécharge l'app ici : ${link}\n\n` +
    `À très vite sur l'eau !\n` +
    `${ctx.inviterPseudo}`
  );
}

/** Fire the WhatsApp chat with a pre-filled body. Returns `true` if
 *  WhatsApp accepted the deep-link (installed & phone reachable). */
async function openWhatsApp(
  phoneE164: string | undefined, body: string,
): Promise<boolean> {
  if (!phoneE164) return false;
  // WhatsApp deep-link : `whatsapp://send?phone=<international>&text=<body>`.
  // The number MUST be in the international format WITHOUT the leading `+`
  // per WhatsApp's URL scheme spec.
  const digits = phoneE164.replace(/[^0-9]/g, "");
  if (!digits) return false;
  const url = `whatsapp://send?phone=${digits}&text=${encodeURIComponent(body)}`;
  try {
    const supported = await Linking.canOpenURL(url);
    if (!supported) return false;
    await Linking.openURL(url);
    return true;
  } catch {
    return false;
  }
}

/** Fire the native SMS composer with body + prefilled recipient.
 *  Falls back to a URL-scheme (`sms:`) on platforms where `expo-sms`
 *  can't check availability quickly. */
async function openSms(
  phoneE164: string | undefined, body: string,
): Promise<boolean> {
  if (!phoneE164) return false;
  try {
    const ok = await SMS.isAvailableAsync();
    if (ok) {
      // `sendSMSAsync` opens the OS composer with everything pre-filled;
      // the promise resolves once the user hits Send OR cancels.
      await SMS.sendSMSAsync([phoneE164], body);
      return true;
    }
  } catch { /* fall through to Linking */ }
  // Fallback : sms: URL scheme. iOS wants `sms:<num>&body=…`,
  // Android wants `smsto:<num>?body=…`.  Both are widely supported.
  const enc = encodeURIComponent(body);
  const url = Platform.OS === "ios"
    ? `sms:${phoneE164}&body=${enc}`
    : `sms:${phoneE164}?body=${enc}`;
  try {
    await Linking.openURL(url);
    return true;
  } catch {
    return false;
  }
}

/**
 * Sequentially try WhatsApp then SMS for a single invitee.
 * `preferSms` swaps the order for users who explicitly asked for SMS-only.
 * Returns which channel actually opened, or `null` if none did.
 */
export async function openInvitationChannels(
  ctx: InviteMessageContext,
  channel: "auto" | "sms" | "whatsapp" = "auto",
): Promise<"whatsapp" | "sms" | null> {
  const body = buildInvitationText(ctx);
  if (channel === "sms") {
    return (await openSms(ctx.contactPhoneE164, body)) ? "sms" : null;
  }
  if (channel === "whatsapp") {
    return (await openWhatsApp(ctx.contactPhoneE164, body)) ? "whatsapp" : null;
  }
  // auto : WhatsApp first (nicer UX, richer formatting), SMS as fallback.
  if (await openWhatsApp(ctx.contactPhoneE164, body)) return "whatsapp";
  if (await openSms(ctx.contactPhoneE164, body)) return "sms";
  return null;
}
