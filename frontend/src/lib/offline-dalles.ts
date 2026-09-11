/**
 * SignalMar — CARTES HORS LIGNE (MASTER PLAN armateur, 08/09/2026).
 *
 * Téléchargement des dalles bathy 20 m (fichiers .npy de l'index OVH, servis
 * par notre backend) DIRECTEMENT SUR LE TÉLÉPHONE (expo-file-system), avec
 * manifeste local (AsyncStorage). Prêt pour les dalles FINES 5 m / 2 m :
 * quand l'index OVH les publiera (clé « tiles_fine »), l'app les récupère
 * automatiquement sur les zones déjà possédées en 20 m (checkFineTiles).
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as FileSystem from "expo-file-system/legacy";

const API_BASE = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";

const MANIFEST_KEY = "sm.offline.dalles";
const DIR = `${FileSystem.documentDirectory ?? ""}dalles/`;

export interface DalleInfo {
  name: string;
  bbox: [number, number, number, number]; // w, s, e, n
  size_bytes: number;
  level?: string;
}

export interface OfflineManifest {
  [name: string]: { bbox: [number, number, number, number]; ts: number; level?: string };
}

export async function getManifest(): Promise<OfflineManifest> {
  try {
    const raw = await AsyncStorage.getItem(MANIFEST_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

async function saveManifest(m: OfflineManifest): Promise<void> {
  await AsyncStorage.setItem(MANIFEST_KEY, JSON.stringify(m));
}

/** Dalles 20 m couvrant le polygone dessiné (interroge l'index OVH serveur). */
export async function listDallesForPolygon(
  pts: { lat: number; lng: number }[],
): Promise<{ tiles: DalleInfo[]; total_bytes: number }> {
  const poly = pts.map((p) => `${p.lat.toFixed(5)},${p.lng.toFixed(5)}`).join(";");
  const r = await fetch(`${API_BASE}/api/tiles/dalles-list?poly=${encodeURIComponent(poly)}`);
  if (!r.ok) throw new Error(`Serveur de dalles indisponible (${r.status}).`);
  return r.json();
}

/** Télécharge les dalles sur l'appareil, avec progression (k, total).
 *  10/09/2026 (note armateur n°1 — « 200 Mo en 3 min 25, connexion fibre ») :
 *  téléchargements PARALLÈLES (5 de front) au lieu de dalle par dalle — la
 *  latence par requête ne s'additionne plus. */
export async function downloadDalles(
  tiles: DalleInfo[],
  onProgress: (done: number, total: number) => void,
  cancel?: { cancelled: boolean },
): Promise<{ done: number; failed: number }> {
  await FileSystem.makeDirectoryAsync(DIR, { intermediates: true }).catch(() => {});
  const manifest = await getManifest();
  let done = 0;
  let failed = 0;
  const queue = [...tiles];
  const worker = async (): Promise<void> => {
    for (;;) {
      if (cancel?.cancelled) return;
      const t = queue.shift();
      if (!t) return;
      const dest = DIR + t.name;
      const already = manifest[t.name] && (await FileSystem.getInfoAsync(dest)).exists;
      if (!already) {
        try {
          const res = await FileSystem.downloadAsync(
            `${API_BASE}/api/tiles/dalles-npy/${t.name}`, dest);
          if (res.status !== 200) throw new Error(String(res.status));
          manifest[t.name] = { bbox: t.bbox, ts: Date.now(), ...(t.level ? { level: t.level } : {}) };
        } catch {
          failed += 1;
          onProgress(done, tiles.length);
          continue;
        }
      } else {
        manifest[t.name] = manifest[t.name] ?? { bbox: t.bbox, ts: Date.now() };
      }
      done += 1;
      onProgress(done, tiles.length);
    }
  };
  const nWorkers = Math.max(1, Math.min(5, tiles.length));
  await Promise.all(Array.from({ length: nWorkers }, () => worker()));
  await saveManifest(manifest);
  return { done, failed };
}

/** 08/09/2026 — DALLES FINES 5 m/2 m : si l'index OVH les publie (clé
 *  « tiles_fine », chaîne PC v3), télécharge automatiquement celles qui
 *  recouvrent les zones DÉJÀ possédées en 20 m. Inerte tant que le serveur
 *  n'en publie pas (liste vide). */
export async function checkFineTiles(
  onProgress?: (done: number, total: number) => void,
): Promise<number> {
  const manifest = await getManifest();
  const owned = Object.values(manifest).filter((m) => !m.level);
  if (!owned.length) return 0;
  const w = Math.min(...owned.map((m) => m.bbox[0]));
  const s = Math.min(...owned.map((m) => m.bbox[1]));
  const e = Math.max(...owned.map((m) => m.bbox[2]));
  const n = Math.max(...owned.map((m) => m.bbox[3]));
  let fine: DalleInfo[] = [];
  try {
    const r = await fetch(`${API_BASE}/api/tiles/dalles-fine-list?bbox=${w},${s},${e},${n}`);
    if (!r.ok) return 0;
    fine = (await r.json()).tiles ?? [];
  } catch {
    return 0;
  }
  // Ne garder que les dalles fines recouvrant une dalle 20 m possédée.
  const wanted = fine.filter((f) =>
    Object.values(manifest).some((m) =>
      !m.level && f.bbox[0] < m.bbox[2] && f.bbox[2] > m.bbox[0] &&
      f.bbox[1] < m.bbox[3] && f.bbox[3] > m.bbox[1]) &&
    !manifest[f.name]);
  if (!wanted.length) return 0;
  const res = await downloadDalles(wanted, onProgress ?? (() => {}));
  return res.done;
}

/** 09/09/2026 (V1.6) — PACK HORS LIGNE complet : balisage + mouillages +
 *  dangers de la zone (jusqu'à 5000 objets), stocké en JSON sur l'appareil. */
export async function downloadSeamarkPack(
  corners: { lat: number; lng: number }[],
): Promise<{ count: number; bytes: number }> {
  const w = Math.min(...corners.map((c) => c.lng));
  const s = Math.min(...corners.map((c) => c.lat));
  const e = Math.max(...corners.map((c) => c.lng));
  const n = Math.max(...corners.map((c) => c.lat));
  const r = await fetch(`${API_BASE}/api/bathy/seamarks?bbox=${w},${s},${e},${n}&limit=5000`);
  if (!r.ok) throw new Error(`Balisage indisponible (${r.status}).`);
  const body = await r.text();
  await FileSystem.makeDirectoryAsync(DIR, { intermediates: true }).catch(() => {});
  const dest = `${DIR}pack_seamarks.json`;
  await FileSystem.writeAsStringAsync(dest, body);
  const count = (JSON.parse(body).marks ?? []).length;
  return { count, bytes: body.length };
}

/** 09/09/2026 (V1.6) — pastille de source : TRUE si le point est couvert par
 *  une dalle téléchargée SUR L'APPAREIL (vert « LOCAL »), sinon « SERVER ». */
export function isLocalCovered(
  manifest: OfflineManifest, lat: number, lng: number,
): boolean {
  return Object.values(manifest).some(
    (m) => lng >= m.bbox[0] && lng <= m.bbox[2] && lat >= m.bbox[1] && lat <= m.bbox[3]);
}

/** Statistiques du stock local (compte + octets). */
export async function offlineStats(): Promise<{ count: number; bytes: number }> {
  const manifest = await getManifest();
  const names = Object.keys(manifest);
  let bytes = 0;
  for (const nm of names) {
    const info = await FileSystem.getInfoAsync(DIR + nm);
    if (info.exists && !info.isDirectory) bytes += info.size ?? 0;
  }
  return { count: names.length, bytes };
}
