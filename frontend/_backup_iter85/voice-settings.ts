// SignalMar — Hook React + storage pour les réglages d'alerte vocale.

import { useEffect, useState, useCallback } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { DEFAULT_VOICE_SETTINGS, type VoiceSettings } from "@/src/lib/voice-alerts";

const KEY = "signalmar.voice-settings.v1";

let memo: VoiceSettings | null = null;
const listeners: Set<(s: VoiceSettings) => void> = new Set();

async function loadFromDisk(): Promise<VoiceSettings> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (!raw) return { ...DEFAULT_VOICE_SETTINGS };
    const parsed = JSON.parse(raw) as Partial<VoiceSettings> & { repCapMigrated?: boolean };
    // Migration 13/07/2026 (2e passe) : plafond des répétitions abaissé à 2
    // (demande user — total diffusé = 1 annonce + N répétitions). L'ancien
    // défaut 1 jamais touché passe au nouveau défaut 2 ; toute valeur > 2
    // (ancien défaut 3) est ramenée à 2 ; un choix délibéré de 0 est conservé.
    if (!parsed.repCapMigrated) {
      if (parsed.repetitions === 1 || parsed.repetitions === undefined) {
        parsed.repetitions = 2;
      }
      parsed.repCapMigrated = true;
      try { await AsyncStorage.setItem(KEY, JSON.stringify(parsed)); } catch { /* noop */ }
    }
    if ((parsed.repetitions ?? 0) > 2) {
      parsed.repetitions = 2;
      try { await AsyncStorage.setItem(KEY, JSON.stringify(parsed)); } catch { /* noop */ }
    }
    // NB : la migration de l'ancien « rayon d'alerte » unique (baseRadiusM,
    // système à 2 rayons pré-10/07) a été RETIRÉE le 12/07 — vestige purgé
    // lors de l'audit du système d'alertes.
    return { ...DEFAULT_VOICE_SETTINGS, ...parsed };
  } catch {
    return { ...DEFAULT_VOICE_SETTINGS };
  }
}

async function persist(s: VoiceSettings) {
  try { await AsyncStorage.setItem(KEY, JSON.stringify(s)); } catch { /* noop */ }
}

export function useVoiceSettings() {
  const [settings, setSettings] = useState<VoiceSettings | null>(memo);

  useEffect(() => {
    if (memo) return;
    let cancelled = false;
    (async () => {
      const s = await loadFromDisk();
      if (cancelled) return;
      memo = s;
      setSettings(s);
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    const fn = (s: VoiceSettings) => setSettings(s);
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  }, []);

  const update = useCallback(async (patch: Partial<VoiceSettings>) => {
    const cur = memo ?? (await loadFromDisk());
    const next = { ...cur, ...patch };
    memo = next;
    await persist(next);
    listeners.forEach((l) => l(next));
  }, []);

  const reset = useCallback(async () => {
    memo = { ...DEFAULT_VOICE_SETTINGS };
    await persist(memo);
    listeners.forEach((l) => l(memo!));
  }, []);

  return { settings: settings ?? DEFAULT_VOICE_SETTINGS, update, reset };
}

/** Lecteur synchrone à utiliser depuis du code hors-React. */
export async function getVoiceSettings(): Promise<VoiceSettings> {
  if (memo) return memo;
  memo = await loadFromDisk();
  return memo;
}
