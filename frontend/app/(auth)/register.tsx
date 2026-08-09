import { Redirect } from "expo-router";

/**
 * Phase A — L'inscription et la connexion sont désormais unifiées dans le
 * flux téléphone + OTP de /(auth)/login (le backend détecte si le numéro
 * existe). Cette route est conservée pour les anciens deep-links.
 */
export default function Register() {
  return <Redirect href="/(auth)/login" />;
}
