// SignalMar — Envoi d'un enregistrement d'écran / capture au SUPPORT
// (13/07/2026, demande armateur pour tests & debugging).
//
// Galerie (vidéos + images) → upload CHUNKÉ 512 Ko (passe sous les limites
// du proxy) → assemblé côté backend dans uploads/support/ + méta Mongo.
// Lecture mémoire-safe : blob.slice + FileReader par chunk (jamais tout le
// fichier en base64 en RAM — leçon du crash OOM photos).

import * as ImagePicker from "expo-image-picker";
import { Alert, Linking, LogBox, Platform } from "react-native";

import { api } from "@/src/api/client";

// Artefact connu du shim web d'expo-image-picker (dev uniquement) : l'input
// fichier est retiré du DOM deux fois après sélection. Sans impact sur
// l'upload — on masque l'overlay LogBox pour ne pas effrayer l'utilisateur.
if (Platform.OS === "web") {
  LogBox.ignoreLogs(["Failed to execute removeChild"]);
}

const CHUNK_SIZE = 96 * 1024; // 96 Ko binaire (~128 Ko en base64)
// 03/08/2026 — les morceaux faisaient 512 Ko (≈683 Ko en base64) : l'ingress
// throttlait (HTTP 429) et l'envoi échouait en mer comme au port. 96 Ko passe.
// Plafond d'upload : la compression vidéo réelle n'est possible qu'à la
// sélection sur iOS (re-encodage MediumQuality par le picker). Sur Android,
// Expo Go ne permet PAS de transcodage → on borne la taille et on guide
// l'utilisateur vers un enregistrement plus court.
const MAX_UPLOAD_BYTES = 100 * 1024 * 1024; // 100 Mo

/** Envoi d'un morceau avec 3 tentatives et attente croissante.
 *  03/08/2026 — un seul ré-essai ne suffisait pas : l'ingress renvoie 429 en
 *  rafale quand la carte télécharge des tuiles en parallèle. */
async function sendChunk(uploadId: string, index: number, b64: string): Promise<void> {
  const waits = [700, 1800, 4000];
  let lastErr: unknown;
  for (let attempt = 0; attempt < waits.length + 1; attempt++) {
    try {
      await api.supportUploadChunk(uploadId, index, b64);
      return;
    } catch (err) {
      lastErr = err;
      if (attempt < waits.length) {
        await new Promise((r) => setTimeout(r, waits[attempt]));
      }
    }
  }
  throw lastErr;
}

function chunkToB64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error);
    reader.onload = () => {
      const s = String(reader.result || "");
      resolve(s.slice(s.indexOf(",") + 1)); // retire le préfixe data:...;base64,
    };
    reader.readAsDataURL(blob);
  });
}

/** Envoie les chunks web : Blob.slice + FileReader (fetch(file://) n'existe
 *  pas sur web pour les fichiers choisis — le picker renvoie déjà un blob). */
async function uploadFromBlob(
  uri: string,
  uploadId: string,
  totalChunks: number,
  size: number,
  onProgress: (pct: number) => void,
): Promise<void> {
  const blob = await (await fetch(uri)).blob();
  for (let i = 0; i < totalChunks; i++) {
    const part = blob.slice(i * CHUNK_SIZE, Math.min(size, (i + 1) * CHUNK_SIZE));
    const b64 = await chunkToB64(part);
    await sendChunk(uploadId, i, b64);
    onProgress(Math.min(99, Math.round(((i + 1) / totalChunks) * 100)));
  }
}

/** Envoie les chunks natifs (iOS/Android) : lecture base64 par tranches via
 *  expo-file-system — fetch(file://).blob() échoue sur téléphone (Network
 *  request failed), c'était la cause du bouton « qui ne fait rien ». */
async function uploadFromNativeFile(
  uri: string,
  uploadId: string,
  totalChunks: number,
  size: number,
  onProgress: (pct: number) => void,
): Promise<void> {
  const FileSystem = await import("expo-file-system/legacy");
  for (let i = 0; i < totalChunks; i++) {
    const b64 = await FileSystem.readAsStringAsync(uri, {
      encoding: FileSystem.EncodingType.Base64,
      position: i * CHUNK_SIZE,
      length: Math.min(CHUNK_SIZE, size - i * CHUNK_SIZE),
    });
    await sendChunk(uploadId, i, b64);
    onProgress(Math.min(99, Math.round(((i + 1) / totalChunks) * 100)));
  }
}

/** Taille du fichier natif (asset.fileSize manque parfois sur Android). */
async function nativeFileSize(uri: string): Promise<number> {
  const FileSystem = await import("expo-file-system/legacy");
  const info = await FileSystem.getInfoAsync(uri, { size: true });
  if (!info.exists || typeof info.size !== "number") {
    throw new Error("Fichier introuvable ou taille inconnue");
  }
  return info.size;
}

/** Demande la permission galerie (contextuel, avec redirection réglages
 *  si refus définitif). Retourne true si accordée. */
async function ensureGalleryPermission(): Promise<boolean> {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (perm.granted) return true;
  if (!perm.canAskAgain) {
    Alert.alert(
      "Accès galerie refusé",
      "Autorisez l'accès aux photos/vidéos dans les réglages pour envoyer un fichier au support.",
      [
        { text: "Annuler", style: "cancel" },
        { text: "Ouvrir les réglages", onPress: () => Linking.openSettings() },
      ],
    );
  }
  return false;
}

/** Upload chunké d'UN asset (image ou vidéo) vers le support.
 *  Retourne false si le fichier dépasse le plafond de taille. */
async function sendAssetToSupport(
  asset: ImagePicker.ImagePickerAsset,
  onProgress: (pct: number) => void,
): Promise<boolean> {
  const mime = asset.mimeType || "application/octet-stream";
  const ext = mime.includes("video") ? "mp4" : mime.includes("png") ? "png" : "jpg";
  const filename = asset.fileName || `enregistrement-${Date.now()}.${ext}`;

  onProgress(1);
  if (Platform.OS === "web") {
    const blob = await (await fetch(asset.uri)).blob();
    const size = blob.size;
    if (!checkSize(size)) return false;
    const totalChunks = Math.max(1, Math.ceil(size / CHUNK_SIZE));
    const { upload_id } = await api.supportUploadInit(filename, mime || blob.type, totalChunks);
    await uploadFromBlob(asset.uri, upload_id, totalChunks, size, onProgress);
    await api.supportUploadComplete(upload_id);
  } else {
    const size = typeof asset.fileSize === "number" && asset.fileSize > 0
      ? asset.fileSize
      : await nativeFileSize(asset.uri);
    if (!checkSize(size)) return false;
    const totalChunks = Math.max(1, Math.ceil(size / CHUNK_SIZE));
    const { upload_id } = await api.supportUploadInit(filename, mime, totalChunks);
    await uploadFromNativeFile(asset.uri, upload_id, totalChunks, size, onProgress);
    await api.supportUploadComplete(upload_id);
  }
  onProgress(100);
  return true;
}

/** Ouvre la galerie puis envoie la vidéo/capture choisie au support.
 *  @param onProgress 0-100 (progression de l'upload).
 *  @returns true si un fichier a été envoyé. */
export async function pickAndSendSupportRecording(
  onProgress: (pct: number) => void,
): Promise<boolean> {
  if (!(await ensureGalleryPermission())) return false;

  const res = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["videos", "images"],
    quality: 0.8,
    // iOS : ré-encodage de la vidéo à la sélection (compression réelle).
    videoExportPreset: ImagePicker.VideoExportPreset.MediumQuality,
    videoQuality: ImagePicker.UIImagePickerControllerQualityType.Medium,
  });
  if (res.canceled || !res.assets?.length) return false;
  return sendAssetToSupport(res.assets[0], onProgress);
}

/** Ouvre la galerie (PHOTOS uniquement, multi-sélection jusqu'à 5) puis
 *  envoie chaque capture d'écran au support, séquentiellement.
 *  @param onProgress 0-100 global (toutes captures confondues).
 *  @returns nombre de captures effectivement envoyées. */
export async function pickAndSendSupportScreenshots(
  onProgress: (pct: number) => void,
): Promise<number> {
  if (!(await ensureGalleryPermission())) return 0;

  const res = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    quality: 0.9,
    allowsMultipleSelection: true,
    selectionLimit: 5,
  });
  if (res.canceled || !res.assets?.length) return 0;

  const assets = res.assets.slice(0, 5);
  let sent = 0;
  for (let i = 0; i < assets.length; i++) {
    const ok = await sendAssetToSupport(assets[i], (pct) => {
      onProgress(Math.min(99, Math.round(((i + pct / 100) / assets.length) * 100)));
    });
    if (ok) sent++;
  }
  onProgress(100);
  return sent;
}

/** Garde-fou taille : alerte claire si le fichier dépasse le plafond. */
function checkSize(size: number): boolean {
  if (size <= MAX_UPLOAD_BYTES) return true;
  Alert.alert(
    "Fichier trop volumineux",
    `Cet enregistrement fait ${(size / (1024 * 1024)).toFixed(0)} Mo (maximum ${MAX_UPLOAD_BYTES / (1024 * 1024)} Mo). ` +
      "Envoyez un enregistrement plus court, ou recadrez la vidéo sur le moment du bug.",
  );
  return false;
}

// ── Capture CARTE avec coordonnées (outil de debug de l'armateur) ─────────
// 03/08/2026 — cet envoi passait par un POST unique de ~400 Ko de base64 vers
// /api/support/screenshot : throttlé par l'ingress (« support screenshot
// failed {"status":429} » dans les logs du terrain, dernière capture reçue à
// 12h28 le 03/08 puis plus rien). Il emprunte désormais le MÊME chemin chunké
// que la galerie, avec le même ré-essai, puis rattache les coordonnées via
// /api/support/screenshot/commit.

/** Découpe une chaîne base64 en morceaux INDÉPENDAMMENT décodables.
 *  Chaque morceau doit être un multiple de 4 caractères base64 (3 octets). */
function sliceB64(b64: string, binChunk: number): string[] {
  const step = Math.ceil(binChunk / 3) * 4;   // multiple de 4 → décodable seul
  const out: string[] = [];
  for (let i = 0; i < b64.length; i += step) out.push(b64.slice(i, i + step));
  return out;
}

export type MapCaptureMeta = {
  lat?: number | null;
  lng?: number | null;
  depth_zh_m?: number | null;
  comment?: string | null;
  route_id?: string | null;
  context?: Record<string, unknown> | null;
};

/** Envoie une capture de la carte (data URL) au support, PAR MORCEAUX.
 *  @param dataUri "data:image/jpeg;base64,…" renvoyé par captureMap()
 *  @param onProgress 0-100
 *  @returns l'identifiant de la capture côté serveur (ex. « S-20260803-… ») */
export async function sendMapCaptureToSupport(
  dataUri: string,
  meta: MapCaptureMeta,
  onProgress: (pct: number) => void,
): Promise<string> {
  const comma = dataUri.indexOf(",");
  const b64 = comma >= 0 ? dataUri.slice(comma + 1) : dataUri;
  const mime = /^data:([^;,]+)/.exec(dataUri)?.[1] || "image/jpeg";
  if (b64.length < 32) throw new Error("Capture vide");

  const parts = sliceB64(b64, CHUNK_SIZE);
  onProgress(1);
  const { upload_id } = await api.supportUploadInit(
    `carte-${Date.now()}.${mime.includes("png") ? "png" : "jpg"}`,
    mime,
    parts.length,
  );
  for (let i = 0; i < parts.length; i++) {
    await sendChunk(upload_id, i, parts[i]);
    onProgress(Math.min(97, Math.round(((i + 1) / parts.length) * 97)));
    // Respiration entre deux morceaux : évite de déclencher le throttling.
    if (i < parts.length - 1) await new Promise((r) => setTimeout(r, 60));
  }
  const res = await api.commitMapSupportScreenshot({ upload_id, mime, ...meta });
  onProgress(100);
  return res.id;
}
