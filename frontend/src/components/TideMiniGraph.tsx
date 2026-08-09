/**
 * SignalMar — MINI-GRAPHE DE MARÉE 24 h (28/07/2026, GO armateur).
 * Affiché sur la RouteCard : courbe de hauteur d'eau (≈/ZH) au port le plus
 * proche de la DESTINATION sur 24 h, avec la zone « PASSABLE » soulignée en
 * vert (hauteur ≥ hauteur requise par la route) — la « fenêtre de tir » se
 * lit d'un coup d'œil. Route passable à toute marée → tout est vert.
 */
import { useEffect, useMemo, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import Svg, { Line, Path, Polyline, Rect } from "react-native-svg";

import { api } from "@/src/api/client";
import { radii, theme } from "@/src/lib/theme";

const H = 56;
const PAD_TOP = 6;
const PAD_BOT = 10;

export function TideMiniGraph(props: {
  lat: number;
  lng: number;
  /** Hauteur de marée requise (m ≈/ZH) — null/0 = passable à toute marée. */
  requiredM: number | null;
}) {
  const { lat, lng, requiredM } = props;
  const [curve, setCurve] = useState<{ port: string; points: { ts: number; h: number }[] } | null>(null);
  const [failed, setFailed] = useState(false);
  const [w, setW] = useState(0);

  useEffect(() => {
    let alive = true;
    setCurve(null);
    setFailed(false);
    api.tideCurve(lat, lng)
      .then((c) => { if (alive) setCurve(c); })
      .catch(() => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [lat, lng]);

  const g = useMemo(() => {
    if (!curve || curve.points.length < 4) return null;
    const pts = curve.points;
    const t0 = pts[0].ts;
    const t1 = pts[pts.length - 1].ts;
    const W = 1000;
    const hMin = Math.min(0, ...pts.map((p) => p.h));
    const hMax = Math.max(requiredM ?? 0, ...pts.map((p) => p.h)) + 0.3;
    const x = (ts: number) => ((ts - t0) / Math.max(1, t1 - t0)) * W;
    const y = (h: number) => PAD_TOP + (1 - (h - hMin) / Math.max(0.1, hMax - hMin)) * (H - PAD_TOP - PAD_BOT);
    const line = pts.map((p) => `${x(p.ts).toFixed(1)},${y(p.h).toFixed(1)}`).join(" ");
    const area = `M${x(pts[0].ts).toFixed(1)},${H} L${line.split(" ").join(" L")} L${x(t1).toFixed(1)},${H} Z`;
    // Zones PASSABLES (h ≥ requis) → barres vertes soulignées en bas.
    const req = requiredM != null && requiredM > 0.01 ? requiredM : null;
    const bands: { x0: number; x1: number }[] = [];
    if (req == null) {
      bands.push({ x0: 0, x1: W });
    } else {
      let start: number | null = null;
      for (let i = 0; i < pts.length; i++) {
        const ok = pts[i].h >= req;
        if (ok && start == null) start = x(pts[i].ts);
        if ((!ok || i === pts.length - 1) && start != null) {
          bands.push({ x0: start, x1: x(pts[i].ts) });
          start = null;
        }
      }
    }
    // Repères horaires : maintenant / +6 h / +12 h / +18 h / +24 h.
    const ticks = [0, 6, 12, 18, 24].map((hh) => ({
      x: (hh / 24) * W,
      label: hh === 0
        ? "maint."
        : new Date((t0 + hh * 3600) * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }),
    }));
    return { W, line, area, yReq: req != null ? y(req) : null, bands, ticks, req, port: curve.port };
  }, [curve, requiredM]);

  if (failed) return null; // marée indisponible : pas de graphe (info déjà ailleurs)
  if (!g) {
    return (
      <View style={styles.wrap}>
        <Text style={styles.loading}>Marée 24 h…</Text>
      </View>
    );
  }
  return (
    <View testID="route-tide-graph">
      <View style={styles.wrap} onLayout={(e) => setW(e.nativeEvent.layout.width)}>
        {w > 0 ? (
          <Svg width={w} height={H} viewBox={`0 0 ${g.W} ${H}`} preserveAspectRatio="none">
            <Path d={g.area} fill="rgba(72,202,228,0.18)" />
            <Polyline points={g.line} fill="none" stroke="#48CAE4" strokeWidth={4} vectorEffect="non-scaling-stroke" />
            {g.yReq != null ? (
              <Line
                x1={0} y1={g.yReq} x2={g.W} y2={g.yReq}
                stroke="#F4A261" strokeWidth={2.5} strokeDasharray="8 7"
                vectorEffect="non-scaling-stroke"
              />
            ) : null}
            {/* Soulignement VERT = fenêtre passable. */}
            {g.bands.map((b, i) => (
              <Rect key={i} x={b.x0} y={H - 6} width={Math.max(4, b.x1 - b.x0)} height={5} rx={2} fill="#22C55E" />
            ))}
            {/* Graduations légères toutes les 6 h. */}
            {g.ticks.slice(1, 4).map((t, i) => (
              <Line
                key={i} x1={t.x} y1={PAD_TOP} x2={t.x} y2={H - PAD_BOT}
                stroke="rgba(232,236,251,0.14)" strokeWidth={1} vectorEffect="non-scaling-stroke"
              />
            ))}
          </Svg>
        ) : null}
      </View>
      <View style={styles.ticksRow}>
        {g.ticks.map((t, i) => (
          <Text key={i} style={styles.tickTxt}>{t.label}</Text>
        ))}
      </View>
      <Text style={styles.caption} numberOfLines={2}>
        {g.req != null
          ? `Marée 24 h (${g.port}) — ▬ vert : passable (≥ +${g.req.toFixed(1)} m).`
          : `Marée 24 h (${g.port}) — route passable à TOUTE marée (calcul à marée basse).`}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: "rgba(255,255,255,0.05)",
    borderRadius: radii.sm,
    overflow: "hidden",
    alignSelf: "stretch",
    height: H,
    justifyContent: "center",
  },
  loading: { color: theme.textMute, fontSize: 10, textAlign: "center" },
  ticksRow: { flexDirection: "row", justifyContent: "space-between", marginTop: 1 },
  tickTxt: { color: theme.textMute, fontSize: 8.5, fontWeight: "700" },
  caption: { color: theme.textDim, fontSize: 10, marginTop: 2, fontWeight: "700" },
});
