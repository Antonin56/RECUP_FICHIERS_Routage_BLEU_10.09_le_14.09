import { storage } from "@/src/utils/storage";
import type { ReportItem } from "@/src/api/client";

const KEY = "signalmar.reports.cache.v2";
const MAX_AGE_HOURS = 12;

type CachePayload = { saved_at: string; reports: ReportItem[] };

export async function saveReportsCache(reports: ReportItem[]) {
  const payload: CachePayload = {
    saved_at: new Date().toISOString(),
    reports,
  };
  await storage.setItem(KEY, JSON.stringify(payload));
}

/** Load cached reports, keeping only entries created in the last `maxHours` hours. */
export async function loadReportsCache(maxHours = MAX_AGE_HOURS): Promise<ReportItem[]> {
  const raw = await storage.getItem<string>(KEY, "");
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw) as CachePayload;
    const cutoff = Date.now() - maxHours * 3600_000;
    return (parsed.reports || []).filter((r) => {
      const t = new Date(r.created_at).getTime();
      return Number.isFinite(t) && t >= cutoff;
    });
  } catch {
    return [];
  }
}

/** 23/07/2026 — purge un signalement SUPPRIMÉ côté serveur (404 sur le
 *  détail) : sinon son marqueur restait cliquable via le cache hors-ligne
 *  (12 h) et rouvrait « Signalement introuvable » en boucle. */
export async function removeReportFromCache(id: string) {
  const raw = await storage.getItem<string>(KEY, "");
  if (!raw) return;
  try {
    const parsed = JSON.parse(raw) as CachePayload;
    const next = (parsed.reports || []).filter((r) => r.id !== id);
    if (next.length === (parsed.reports || []).length) return;
    await storage.setItem(KEY, JSON.stringify({ ...parsed, reports: next }));
  } catch {
    /* cache illisible : ignoré */
  }
}
