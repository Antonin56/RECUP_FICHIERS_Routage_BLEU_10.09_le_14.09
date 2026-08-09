// SignalMar — Formatage unifié des coordonnées GPS + helpers temps.
//
// FORMAT PRINCIPAL NAUTIQUE (DM — degrés + minutes décimales) :
//   "47°29.092'N  2°34.807'W"  — utilisé par Navionics & cartes marines
//
// FORMAT DECIMAL (DD) — pour coller dans Google Maps :
//   "47.48487, -2.58012"
//
// Bonus : DMS — degrés / minutes / secondes.
//
// Toutes les fonctions gèrent l'arrondi correctement (60.000' → bascule
// sur le degré supérieur, jamais de "60.000'").

const NBSP = "\u00A0";

function fmtDM(absVal: number, hemiPos: "N" | "E", hemiNeg: "S" | "W", original: number): string {
  let deg = Math.floor(absVal);
  let min = (absVal - deg) * 60;
  min = Math.round(min * 1000) / 1000;
  if (min >= 60) {
    min -= 60;
    deg += 1;
  }
  const hemi = original >= 0 ? hemiPos : hemiNeg;
  const minStr = min.toFixed(3).padStart(6, "0");
  return `${deg}°${minStr}'${hemi}`;
}

/** Format nautique standard — "47°29.092'N  2°34.807'W". */
export function formatDM(lat: number, lng: number): string {
  return `${fmtDM(Math.abs(lat), "N", "S", lat)}${NBSP}${NBSP}${fmtDM(Math.abs(lng), "E", "W", lng)}`;
}

/** Format décimal — "47.48487, -2.58012". */
export function formatDD(lat: number, lng: number): string {
  return `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
}

/** Format degrés/minutes/secondes (peu utilisé en mer). */
export function formatDMS(lat: number, lng: number): string {
  function one(v: number, hp: "N" | "E", hn: "S" | "W") {
    const a = Math.abs(v);
    let deg = Math.floor(a);
    const minF = (a - deg) * 60;
    let min = Math.floor(minF);
    let sec = Math.round((minF - min) * 60 * 10) / 10;
    if (sec >= 60) { sec -= 60; min += 1; }
    if (min >= 60) { min -= 60; deg += 1; }
    const hemi = v >= 0 ? hp : hn;
    return `${deg}°${String(min).padStart(2, "0")}'${sec.toFixed(1).padStart(4, "0")}"${hemi}`;
  }
  return `${one(lat, "N", "S")}${NBSP}${NBSP}${one(lng, "E", "W")}`;
}

export function formatDMLat(lat: number): string {
  return fmtDM(Math.abs(lat), "N", "S", lat);
}
export function formatDMLng(lng: number): string {
  return fmtDM(Math.abs(lng), "E", "W", lng);
}

// ── Helpers temps (conservés depuis l'ancienne version) ──────────────────

/** @deprecated — utiliser formatDMS(lat, lng) pour les coordonnées complètes. */
export function toDMS(value: number, isLat: boolean): string {
  const dir = value >= 0 ? (isLat ? "N" : "E") : isLat ? "S" : "W";
  const abs = Math.abs(value);
  const deg = Math.floor(abs);
  const minFloat = (abs - deg) * 60;
  const min = Math.floor(minFloat);
  const sec = ((minFloat - min) * 60).toFixed(1);
  return `${deg}° ${min}' ${sec}" ${dir}`;
}

/** @deprecated — utiliser formatDD(lat, lng). */
export function toDecimal(value: number): string {
  return value.toFixed(5) + "°";
}

export function formatTimeAgo(iso: string | Date): string {
  let d: Date;
  if (typeof iso === "string") {
    const s = iso.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z";
    d = new Date(s);
  } else {
    d = iso;
  }
  const sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (sec < 5) return "à l'instant";
  if (sec < 60) return `il y a quelques secondes`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `il y a ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `il y a ${h} h`;
  const day = Math.floor(h / 24);
  return `il y a ${day} j`;
}
