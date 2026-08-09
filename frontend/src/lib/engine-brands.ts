// SignalMar — Marques de moteurs marins (28/07/2026, demande armateur).
// Les marques « prioritaires » sont affichées EN TÊTE dans l'ordre imposé ;
// le reste suit par ordre alphabétique. Recherche par préfixe/inclusion.

/** Hors-bord — tête de liste imposée : Mercury, Yamaha, Suzuki, Honda. */
export const OUTBOARD_TOP = ["Mercury", "Yamaha", "Suzuki", "Honda"];
export const OUTBOARD_REST = [
  "Evinrude",
  "Force",
  "Hangkai",
  "Hidea",
  "Johnson",
  "Mariner",
  "Nissan Marine",
  "Parsun",
  "Sea-Pro",
  "Selva Marine",
  "Tohatsu",
  "Torqeedo",
  "Yamabisi",
].sort((a, b) => a.localeCompare(b, "fr"));

/** Inboard — tête de liste imposée : Volvo Penta, Yanmar, Nanni, Vetus. */
export const INBOARD_TOP = ["Volvo Penta", "Yanmar", "Nanni", "Vetus"];
export const INBOARD_REST = [
  "Beta Marine",
  "Caterpillar",
  "Craftsman Marine",
  "Cummins",
  "FPT (Iveco)",
  "John Deere",
  "Lombardini Marine",
  "MAN",
  "MerCruiser",
  "Mercury Diesel",
  "Mitsubishi",
  "Perkins",
  "Scania",
  "Solé Diesel",
  "Steyr Motors",
  "Westerbeke",
].sort((a, b) => a.localeCompare(b, "fr"));

export type EngineKind = "outboard" | "inboard";

export function brandsFor(kind: EngineKind): string[] {
  return kind === "outboard"
    ? [...OUTBOARD_TOP, ...OUTBOARD_REST]
    : [...INBOARD_TOP, ...INBOARD_REST];
}

/** Filtre par saisie : préfixe d'abord (ordre de liste conservé), puis
 *  inclusion. Saisie vide → liste complète (tête imposée en premier). */
export function filterBrands(kind: EngineKind, query: string): string[] {
  const all = brandsFor(kind);
  const q = query.trim().toLowerCase();
  if (!q) return all;
  const starts = all.filter((b) => b.toLowerCase().startsWith(q));
  const contains = all.filter((b) => !b.toLowerCase().startsWith(q) && b.toLowerCase().includes(q));
  return [...starts, ...contains];
}
