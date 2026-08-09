// SignalMar — Helper partagé : choisir une photo dans la galerie et
// l'uploader comme avatar. Utilisé par l'onglet Profil et la page Abonnement.

import * as ImagePicker from "expo-image-picker";

import { api, type User } from "@/src/api/client";
import { toDataUri } from "@/src/lib/image-utils";
import { showToast } from "@/src/components/Toast";

/**
 * Ouvre la galerie (avec le contrat de permission), upload l'avatar.
 * @returns le user mis à jour, ou null si annulé / permission refusée.
 * @throws en cas d'échec de l'upload (à catcher par l'appelant).
 */
export async function pickAndUploadAvatar(): Promise<User | null> {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!perm.granted) {
    showToast("error", "Accès photos refusé");
    return null;
  }
  const r = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ImagePicker.MediaTypeOptions.Images,
    quality: 1,
    allowsEditing: true,
    aspect: [1, 1],
    exif: false,
  });
  if (r.canceled) return null;
  const asset = r.assets?.[0];
  if (!asset?.uri) return null;
  // FIX crash 11/07 : redimensionner AVANT l'encodage base64 (OOM Android
  // sur photos pleine résolution).
  const dataUri = await toDataUri(asset.uri, { maxWidth: 512 });
  return api.uploadAvatar(dataUri);
}
