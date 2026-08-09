/**
 * SignalMar — Comparaison A/B de deux tracés de route (02/08/2026).
 *
 * Demande armateur : recalculer une route enregistrée avec un AUTRE moteur
 * puis « mettre en évidence sur la carte les variantes entre les 2 routes ».
 *
 * Méthode : les deux tracés sont densifiés (échantillon tous les ~40 m) puis
 * chaque échantillon est comparé à la polyligne opposée. Les suites
 * d'échantillons distants de plus de `thresholdM` forment les ÉCARTS — ce
 * sont eux qui seront surlignés sur la carte, côté référence ET côté variante.
 */
export type LatLng = { lat: number; lng: number };

const M_PER_DEG_LAT = 110_574;

function mPerDegLng(lat: number): number {
  return 111_320 * Math.cos((lat * Math.PI) / 180);
}

function segDistM(p: LatLng, a: LatLng, b: LatLng, mlng: number): number {
  const ax = (a.lng - p.lng) * mlng;
  const ay = (a.lat - p.lat) * M_PER_DEG_LAT;
  const bx = (b.lng - p.lng) * mlng;
  const by = (b.lat - p.lat) * M_PER_DEG_LAT;
  const dx = bx - ax;
  const dy = by - ay;
  const l2 = dx * dx + dy * dy;
  if (l2 <= 1e-9) return Math.hypot(ax, ay);
  const t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / l2));
  return Math.hypot(ax + t * dx, ay + t * dy);
}

function distToLineM(p: LatLng, line: LatLng[], mlng: number): number {
  let best = Infinity;
  for (let i = 0; i < line.length - 1; i++) {
    const d = segDistM(p, line[i], line[i + 1], mlng);
    if (d < best) best = d;
  }
  return best;
}

/** Échantillonne la polyligne tous les `stepM` mètres (bornes incluses). */
function densify(line: LatLng[], stepM: number, maxPts: number): LatLng[] {
  const out: LatLng[] = [line[0]];
  const mlng = mPerDegLng(line[0].lat);
  for (let i = 0; i < line.length - 1; i++) {
    const a = line[i];
    const b = line[i + 1];
    const len = Math.hypot((b.lat - a.lat) * M_PER_DEG_LAT, (b.lng - a.lng) * mlng);
    const n = Math.max(1, Math.ceil(len / stepM));
    for (let k = 1; k <= n; k++) {
      const t = k / n;
      out.push({ lat: a.lat + (b.lat - a.lat) * t, lng: a.lng + (b.lng - a.lng) * t });
    }
    if (out.length > maxPts) break;
  }
  return out;
}

export type RouteDiff = {
  /** Portions du tracé de RÉFÉRENCE absentes de la variante. */
  diffBase: LatLng[][];
  /** Portions de la VARIANTE absentes de la référence. */
  diffVariant: LatLng[][];
  /** Écart maximal mesuré entre les deux tracés (m). */
  maxDevM: number;
  /** Point du plus grand écart sur chaque tracé (ancrage des étiquettes). */
  anchorBase: LatLng | null;
  anchorVariant: LatLng | null;
  /** Aucun écart au-delà du seuil → les deux moteurs produisent le même tracé. */
  identical: boolean;
};

function runsAbove(
  samples: LatLng[], other: LatLng[], thresholdM: number, mlng: number,
): { runs: LatLng[][]; maxDev: number; anchor: LatLng | null } {
  const runs: LatLng[][] = [];
  let cur: LatLng[] = [];
  let maxDev = 0;
  let anchor: LatLng | null = null;
  for (let i = 0; i < samples.length; i++) {
    const d = distToLineM(samples[i], other, mlng);
    if (d > maxDev) {
      maxDev = d;
      anchor = samples[i];
    }
    if (d > thresholdM) {
      // On garde l'échantillon précédent pour raccrocher visuellement l'écart
      // au tracé commun.
      if (!cur.length && i > 0) cur.push(samples[i - 1]);
      cur.push(samples[i]);
    } else if (cur.length) {
      cur.push(samples[i]);
      if (cur.length >= 2) runs.push(cur);
      cur = [];
    }
  }
  if (cur.length >= 2) runs.push(cur);
  return { runs, maxDev, anchor };
}

export function compareRoutes(
  base: LatLng[], variant: LatLng[], thresholdM = 25,
): RouteDiff {
  const empty: RouteDiff = {
    diffBase: [], diffVariant: [], maxDevM: 0,
    anchorBase: null, anchorVariant: null, identical: true,
  };
  if (base.length < 2 || variant.length < 2) return empty;
  const mlng = mPerDegLng(base[0].lat);
  const sb = densify(base, 40, 4000);
  const sv = densify(variant, 40, 4000);
  const rb = runsAbove(sb, variant, thresholdM, mlng);
  const rv = runsAbove(sv, base, thresholdM, mlng);
  const maxDevM = Math.max(rb.maxDev, rv.maxDev);
  const identical = rb.runs.length === 0 && rv.runs.length === 0;
  const mid = (l: LatLng[]) => l[Math.floor(l.length / 2)];
  return {
    diffBase: rb.runs,
    diffVariant: rv.runs,
    maxDevM,
    anchorBase: identical ? mid(base) : rb.anchor ?? mid(base),
    anchorVariant: identical ? mid(variant) : rv.anchor ?? mid(variant),
    identical,
  };
}

/** Nombre de zones de divergence (max des deux sens). */
export function diffCount(d: RouteDiff): number {
  return Math.max(d.diffBase.length, d.diffVariant.length);
}
