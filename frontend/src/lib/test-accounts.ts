/**
 * Comptes de test / avancés (whitelist QA) — dupliquée côté backend dans
 * routers/dev_switch.py. Utilisée pour : la tuile « Comptes de test »,
 * l'affichage complet de la page Diagnostic, etc.
 */
const TEST_ACCOUNT_EMAILS = new Set([
  "antoninlepinay@gmail.com",
  "contact@accasteo.com",
  "aodren.legrouix@gmail.com",
  "mylene.audebert@gmail.com",
  "niosso.aq@gmail.com",
]);

export function isTestAccount(email?: string | null): boolean {
  return !!email && TEST_ACCOUNT_EMAILS.has(email.toLowerCase());
}
