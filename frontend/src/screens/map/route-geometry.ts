// SignalMar — helpers géométriques PURS de l'écran carte.
// Découpé de app/(tabs)/map.tsx le 27/08/2026 (refactor map.tsx) :
// déplacement PUR, aucun changement fonctionnel.

// 26/07 — ÉDITION DE ROUTE : segment le plus proche d'un point (m + index).
export function nearestSegOnRoute(
  lat: number, lng: number, wps: { lat: number; lng: number }[],
): { distM: number; segIdx: number } {
  const mLat = 111320;
  const mLng = 111320 * Math.cos((lat * Math.PI) / 180);
  let best = { distM: Infinity, segIdx: 0 };
  for (let i = 0; i < wps.length - 1; i++) {
    const ax = (wps[i].lng - lng) * mLng, ay = (wps[i].lat - lat) * mLat;
    const bx = (wps[i + 1].lng - lng) * mLng, by = (wps[i + 1].lat - lat) * mLat;
    const dx = bx - ax, dy = by - ay;
    const l2 = dx * dx + dy * dy;
    const t = l2 > 0 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / l2)) : 0;
    const d = Math.hypot(ax + t * dx, ay + t * dy);
    if (d < best.distM) best = { distM: d, segIdx: i };
  }
  return best;
}

// 11/08 (règle armateur) — ÉDITION : seul le waypoint LE PLUS PROCHE de la
// zone touchée devient éditable (les autres restent de simples repères).
export function nearestWpIdx(
  lat: number, lng: number, wps: { lat: number; lng: number }[],
): number {
  const mLat = 111320;
  const mLng = 111320 * Math.cos((lat * Math.PI) / 180);
  let best = 0, bestD = Infinity;
  for (let i = 0; i < wps.length; i++) {
    const d = Math.hypot((wps[i].lng - lng) * mLng, (wps[i].lat - lat) * mLat);
    if (d < bestD) { bestD = d; best = i; }
  }
  return best;
}
