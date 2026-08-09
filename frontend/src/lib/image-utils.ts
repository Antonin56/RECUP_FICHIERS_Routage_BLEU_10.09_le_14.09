// SignalMar — Compression/redimensionnement d'images (11/07/2026, refonte 14/07/2026).
//
// FIX crash Android #1 (11/07) : demander `base64: true` directement à
// expo-image-picker encode la photo PLEINE RÉSOLUTION → OOM → crash.
//
// FIX crash Android #2 (14/07, retour terrain armateur — Samsung A52s 64 Mpx) :
// `manipulateAsync` décodait quand même le bitmap PLEINE RÉSOLUTION en RAM
// (Glide sans limite de taille, issue expo #36861) avant de le réduire →
// ~256 Mo pour une photo 64 Mpx → OOM NATIF non catchable dans Expo Go
// (pas de largeHeap) → l'app était TUÉE au moment d'ajouter une photo.
// Solution : décodage BORNÉ via `Image.loadAsync(uri, { maxWidth, maxHeight })`
// (expo-image, downsampling natif — la pleine résolution n'entre JAMAIS en
// mémoire), puis encodage JPEG+base64 via la nouvelle API objet
// d'expo-image-manipulator (interop SharedRef). Web : ancien chemin canvas
// conservé (aucun risque OOM, loadAsync web ne supporte pas maxWidth).

import { Platform } from "react-native";
import { Image } from "expo-image";
import {
  ImageManipulator,
  manipulateAsync,
  SaveFormat,
  type ImageRef,
} from "expo-image-manipulator";

/**
 * Redimensionne (largeur max) + compresse + encode en data-URI base64,
 * sans jamais décoder la pleine résolution en mémoire (Android/iOS).
 * @throws en cas d'échec (à catcher par l'appelant).
 */
export async function toDataUri(
  uri: string,
  opts?: { maxWidth?: number; compress?: number },
): Promise<string> {
  const maxWidth = opts?.maxWidth ?? 1280;
  const compress = opts?.compress ?? 0.7;

  if (Platform.OS === "web") {
    // Web : décodage canvas, pas de contrainte mémoire — chemin historique.
    const out = await manipulateAsync(
      uri,
      [{ resize: { width: maxWidth } }],
      { compress, format: SaveFormat.JPEG, base64: true },
    );
    if (!out.base64) throw new Error("Encodage de l'image impossible");
    return `data:image/jpeg;base64,${out.base64}`;
  }

  // Natif : 1) décodage BORNÉ (downsample pendant le décodage — jamais plus
  // de maxWidth×maxWidth pixels en RAM, même pour une photo 64 Mpx).
  const decoded = await Image.loadAsync({ uri }, { maxWidth, maxHeight: maxWidth });
  let rendered: ImageRef | null = null;
  try {
    // 2) encodage JPEG + base64 (aucune transformation : déjà à la bonne taille).
    rendered = await ImageManipulator.manipulate(decoded).renderAsync();
    const saved = await rendered.saveAsync({
      base64: true,
      compress,
      format: SaveFormat.JPEG,
    });
    if (!saved.base64) throw new Error("Encodage de l'image impossible");
    return `data:image/jpeg;base64,${saved.base64}`;
  } finally {
    // 3) libération immédiate des bitmaps natifs.
    try { rendered?.release(); } catch { /* noop */ }
    try { decoded.release(); } catch { /* noop */ }
  }
}
