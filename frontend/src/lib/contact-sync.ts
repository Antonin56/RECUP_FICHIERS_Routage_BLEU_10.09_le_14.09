/**
 * Phase 4.2 — Contact sync helpers.
 *
 * Privacy-first pipeline:
 *   1. Read the phone address book locally via `expo-contacts` (permission
 *      granted by the user, contextual pre-prompt).
 *   2. Normalise every raw number into E.164 with `libphonenumber-js`
 *      (default country = user locale, fallback FR).
 *   3. Hash each E.164 string with SHA-256 (via `expo-crypto`) so the
 *      raw numbers *never* leave the device — only irreversible digests
 *      travel to the backend.
 *   4. POST the hashes to `/api/contacts/match` in batches of 500.
 *   5. Merge server matches back with the local contact metadata (name,
 *      picture) so the UI can render "Jean · Marin niveau 3" nicely.
 *
 * Anything unrelated to the maritime app (contacts without phone, invalid
 * or short-code numbers) is silently discarded — never surface junk data
 * to the user.
 */
import * as Contacts from "expo-contacts";
import * as Crypto from "expo-crypto";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { parsePhoneNumberFromString, type CountryCode } from "libphonenumber-js/max";
import { getLocales } from "expo-localization";

import { api, type ContactMatch } from "@/src/api/client";

// ── Cache local du carnet (11/07/2026) ─────────────────────────────────────
// La lecture + normalisation E.164 + hash SHA-256 de tout le carnet est
// LENTE (plusieurs secondes sur un gros carnet). On met donc le résultat en
// cache 30 jours ; toutes les recherches de contacts piochent dedans.
// Rafraîchissement : automatique à l'expiration, ou manuel via le bouton
// « Mettre à jour » (ContactsRefreshButton) → repart pour 30 jours.
const CONTACTS_CACHE_KEY = "signalmar.contacts-cache.v1";
export const CONTACTS_CACHE_TTL_DAYS = 30;
const CONTACTS_CACHE_TTL_MS = CONTACTS_CACHE_TTL_DAYS * 24 * 3600 * 1000;

/** Metadata we keep locally per phone hash (never sent to the backend). */
export interface LocalPhoneInfo {
  hash: string;
  e164: string;
  displayName: string;
  contactId: string;
  image?: string;
}

export interface MergedContactMatch extends ContactMatch {
  local: LocalPhoneInfo;
}

/** Best-effort default region for phone parsing. Falls back to FR. */
function defaultCountry(): CountryCode {
  try {
    const locales = getLocales();
    const region = locales?.[0]?.regionCode;
    if (region && region.length === 2) return region.toUpperCase() as CountryCode;
  } catch { /* fallback below */ }
  return "FR";
}

/** SHA-256(text) → 64-char lowercase hex (matches Python `sha256().hexdigest()`). */
async function sha256Hex(text: string): Promise<string> {
  return Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, text, {
    encoding: Crypto.CryptoEncoding.HEX,
  });
}

/**
 * Read all contacts from the device, normalise to E.164 + hash.
 * Requires that `Contacts.getPermissionsAsync()` has already granted access —
 * the caller is responsible for the permission dance (see UX contract).
 */
async function readContactsFromDevice(): Promise<LocalPhoneInfo[]> {
  const region = defaultCountry();
  const { data } = await Contacts.getContactsAsync({
    fields: [
      Contacts.Fields.PhoneNumbers,
      Contacts.Fields.Name,
      Contacts.Fields.Image,
    ],
    pageSize: 0, // 0 = all
  });

  const out: LocalPhoneInfo[] = [];
  const seenHashes = new Set<string>();
  for (const c of data) {
    if (!c.phoneNumbers?.length) continue;
    const displayName =
      c.name?.trim() ||
      [c.firstName, c.lastName].filter(Boolean).join(" ").trim() ||
      "Contact";
    for (const p of c.phoneNumbers) {
      const raw = (p.number || "").trim();
      if (!raw) continue;
      const parsed = parsePhoneNumberFromString(raw, region);
      // Only keep numbers we can normalise to E.164 AND that are plausibly
      // valid (avoids emergency numbers, short codes, etc.).
      if (!parsed || !parsed.isPossible()) continue;
      const e164 = parsed.number; // canonical +33... form
      const hash = await sha256Hex(e164);
      if (seenHashes.has(hash)) continue; // dedup across contacts
      seenHashes.add(hash);
      out.push({
        hash,
        e164,
        displayName,
        contactId: String(c.id ?? ""),
        image: c.image?.uri,
      });
    }
  }
  return out;
}

/**
 * Point d'entrée UNIQUE pour lire les contacts : cache-first (TTL 30 j).
 * `forceRefresh` relit le carnet du téléphone et repart pour 30 jours.
 */
export async function loadLocalContacts(
  opts?: { forceRefresh?: boolean },
): Promise<LocalPhoneInfo[]> {
  if (!opts?.forceRefresh) {
    try {
      const raw = await AsyncStorage.getItem(CONTACTS_CACHE_KEY);
      if (raw) {
        const cached = JSON.parse(raw) as { savedAt: number; contacts: LocalPhoneInfo[] };
        if (
          Array.isArray(cached.contacts) &&
          cached.contacts.length > 0 &&
          Date.now() - (cached.savedAt || 0) < CONTACTS_CACHE_TTL_MS
        ) {
          return cached.contacts;
        }
      }
    } catch { /* cache corrompu → relecture device ci-dessous */ }
  }
  const contacts = await readContactsFromDevice();
  try {
    await AsyncStorage.setItem(
      CONTACTS_CACHE_KEY,
      JSON.stringify({ savedAt: Date.now(), contacts }),
    );
  } catch { /* stockage plein — non bloquant, on renvoie quand même */ }
  return contacts;
}

/** Date (ms epoch) de la dernière lecture du carnet — null si jamais lue. */
export async function contactsCacheSavedAt(): Promise<number | null> {
  try {
    const raw = await AsyncStorage.getItem(CONTACTS_CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw) as { savedAt?: number };
    return typeof cached.savedAt === "number" ? cached.savedAt : null;
  } catch { return null; }
}

/**
 * Ask the backend which hashes belong to existing SignalMar users, then
 * merge the server response with the local metadata so the UI can render
 * the address-book name AND the marine pseudo.
 */
export async function matchContactsAgainstServer(
  local: LocalPhoneInfo[],
): Promise<MergedContactMatch[]> {
  if (!local.length) return [];
  const byHash = new Map(local.map((l) => [l.hash, l]));
  const hashes = [...byHash.keys()];

  // /contacts/match caps at 500 per call — batch just in case.
  const BATCH = 500;
  const all: ContactMatch[] = [];
  for (let i = 0; i < hashes.length; i += BATCH) {
    const chunk = hashes.slice(i, i + BATCH);
    const { matches } = await api.contactsMatch(chunk);
    all.push(...matches);
  }
  const merged: MergedContactMatch[] = [];
  for (const m of all) {
    const info = byHash.get(m.phone_hash);
    if (!info) continue;
    merged.push({ ...m, local: info });
  }
  // Sort by local display name for a stable UX.
  merged.sort((a, b) => a.local.displayName.localeCompare(b.local.displayName));
  return merged;
}

/**
 * Best-effort permission flow that respects the app-wide UX contract:
 *   - Never re-prompt if `canAskAgain` is false; instead the caller
 *     shows an "Open settings" button.
 *   - Returns a triplet (granted, canAskAgain) so the UI can react.
 */
export async function requestContactsPermission(): Promise<{
  granted: boolean;
  canAskAgain: boolean;
}> {
  const cur = await Contacts.getPermissionsAsync();
  if (cur.status === "granted") return { granted: true, canAskAgain: true };
  if (!cur.canAskAgain) return { granted: false, canAskAgain: false };
  const req = await Contacts.requestPermissionsAsync();
  return { granted: req.status === "granted", canAskAgain: req.canAskAgain !== false };
}
