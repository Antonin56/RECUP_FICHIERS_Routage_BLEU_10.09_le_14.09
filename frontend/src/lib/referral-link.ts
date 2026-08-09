/**
 * Phase B — Deep-link referral capture.
 *
 * On cold start OR when a URL is opened while the app is running,
 * we extract the referrer code from any of these formats:
 *
 *   https://signalmar.app/i/XXXXXX
 *   https://signalmar.app/?ref=XXXXXX
 *   signalmar://invite?ref=XXXXXX
 *
 * The code is persisted in AsyncStorage (`@signalmar/pending_ref`) so
 * that even if the user takes 30 minutes to finish registration, we
 * still credit the parrain when they submit the signup form.
 *
 * The registration screen reads this key at submit-time and passes
 * the value in the `referral_code` field of the /auth/register
 * request. Once the account is created, the key is cleared so a
 * subsequent share can't re-attribute an existing user.
 *
 * The `usePendingReferral()` hook is passive — it only writes to
 * AsyncStorage. No navigation happens here (the deep-link may fire
 * before Root layout is even ready).
 */
import { useEffect } from "react";
import { Linking } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { logger } from "@/src/lib/logger";

export const PENDING_REF_KEY = "@signalmar/pending_ref";

/** Extract the referrer code from any URL variant we accept. */
export function parseReferrerCode(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    // 1. `/i/<code>` path — the canonical universal-link format.
    const m1 = url.match(/\/i\/([A-Za-z0-9]{4,16})\b/i);
    if (m1) return m1[1].toUpperCase();
    // 2. `?ref=<code>` query param — universal-link fallback used by
    //    generic app share.
    const m2 = url.match(/[?&]ref=([A-Za-z0-9]{4,16})\b/i);
    if (m2) return m2[1].toUpperCase();
    return null;
  } catch {
    return null;
  }
}

/** Store a code in AsyncStorage — used at registration time. */
export async function readPendingRef(): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(PENDING_REF_KEY);
  } catch { return null; }
}

export async function clearPendingRef(): Promise<void> {
  try { await AsyncStorage.removeItem(PENDING_REF_KEY); } catch { /* noop */ }
}

async function captureFromUrl(url: string | null): Promise<void> {
  const code = parseReferrerCode(url);
  if (!code) return;
  try {
    await AsyncStorage.setItem(PENDING_REF_KEY, code);
    logger.event("app", "referral_captured_from_link", { code });
  } catch (e) {
    logger.error("app", "referral_capture_failed", { error: String(e) });
  }
}

/**
 * Hook used at the root layout: subscribes to `Linking` events and also
 * checks `getInitialURL()` on mount so cold-start links are caught.
 *
 * Idempotent: running this multiple times only re-attaches one listener
 * (React unsubscribes on unmount).
 */
export function usePendingReferral(): void {
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const initial = await Linking.getInitialURL();
      if (!cancelled) await captureFromUrl(initial);
    })();
    const sub = Linking.addEventListener("url", ({ url }) => {
      void captureFromUrl(url);
    });
    return () => {
      cancelled = true;
      sub.remove();
    };
  }, []);
}
