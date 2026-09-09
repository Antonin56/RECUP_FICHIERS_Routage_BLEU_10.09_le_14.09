/**
 * SignalMar — Carte de route calculée (V2 phase N1, 20/07/2026).
 *
 * Panneau compact affiché en bas de la carte quand une route sûre est
 * active : distance (km + NM), profondeur mini rencontrée, PROFIL DE
 * PROFONDEUR le long de la route (mini-graphe SVG, idée validée par
 * l'armateur) avec seuil tirant d'eau + marge en rouge et zones limites
 * surlignées, avertissements éventuels, bouton fermer (efface la route).
 */
import { useEffect, useMemo, useState } from "react";
import * as Clipboard from "expo-clipboard";
import {
  ActivityIndicator, KeyboardAvoidingView, Modal, Platform, StyleSheet,
  Text, TextInput, TouchableOpacity, View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import Svg, { Line, Path, Polyline } from "react-native-svg";

import { api, type ComputedRoute } from "@/src/api/client";
import { TideMiniGraph } from "@/src/components/TideMiniGraph";
import { radii, spacing, theme } from "@/src/lib/theme";
import { showToast } from "@/src/components/Toast";

const CHART_H = 64;

// 27/08/2026 (ordre armateur) — PROFIL DE PROFONDEUR MASQUÉ dans la fiche de
// détail : la courbe bleue de la colonne d'eau le long du tracé, le seuil
// rouge en pointillés ET la légende « Fond mini / Seuil » ne sont plus
// affichés. TOUT LE CODE EST CONSERVÉ (calcul + rendu) : repasser ce drapeau
// à true pour réafficher le graphe à l'identique.
const SHOW_DEPTH_PROFILE = false;

/** 26/07 — « HH:MM » (+ « demain » si autre jour) pour les fenêtres de marée. */
function fmtTideTs(ts: number): string {
  const d = new Date(ts * 1000);
  const t = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  return d.getDate() !== new Date().getDate() ? `${t} demain` : t;
}

function fmtDist(m: number, unit: "km" | "nm"): string {
  const km = m / 1000;
  const nm = m / 1852;
  return unit === "nm"
    ? `${nm.toFixed(1)} NM · ${km.toFixed(1)} km`
    : `${km.toFixed(1)} km · ${nm.toFixed(1)} NM`;
}

export function RouteCard(props: {
  route: ComputedRoute;
  unit: "km" | "nm";
  /** 08/09/2026 — tirant d'eau du bateau (bandeau « Route conseillée »). */
  draftM?: number | null;
  /** Masque la fenêtre (la ROUTE RESTE affichée — 21/07, règle armateur). */
  onClose: () => void;
  /** Réduit en mini-pill (distance seule). */
  onMinimize: () => void;
  /** 22/07 — ouvre le dialogue « Enregistrer la route » (nom). */
  onSave?: () => void;
  /** 08/09/2026 — menu dépliable : Modifier (mode édition du tracé). */
  onEdit?: () => void;
  /** 08/09/2026 — menu dépliable : Partager (résumé texte). */
  onShare?: () => void;
  /** 08/09/2026 — menu dépliable : Supprimer (efface la route). */
  onDelete?: () => void;
  /** 23/07 — démarre le SUIVI DE ROUTE (panneau cap/ETA + grisage). */
  onNavigate?: () => void;
  /** 09/09/2026 (V1.6) — temps de calcul définitif, affiché sous le titre. */
  computeS?: number | null;
  /** 26/07 — tap sur la ZONE ROUGE du profil → centre la carte dessus. */
  onFocusDanger?: (lat: number, lng: number, spanM: number) => void;
  /** 02/08/2026 (demande armateur) — A/B TESTING : recalcule cette route avec
   *  un autre moteur et compare les deux tracés sur la carte. */
  onCompareEngine?: () => void;
}) {
  const { route, unit, draftM, onClose, onMinimize, onSave, onEdit, onShare, onDelete, onNavigate, computeS, onFocusDanger, onCompareEngine } = props;
  // 08/09/2026 (remise à plat armateur) — infobulle « i » de décharge de
  // responsabilité + menu dépliable (Enregistrer/Modifier/Partager/Supprimer).
  const [infoOpen, setInfoOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  // Largeur MESURÉE du conteneur : react-native-svg web interprète mal
  // width="100%" (la carte gonflait à la largeur du viewBox — bug iter94).
  const [chartW, setChartW] = useState(0);
  // 14/08/2026 (demande armateur) — signalement « balisage non respecté ».
  const [reportOpen, setReportOpen] = useState(false);
  // 04/09/2026 (ordre armateur, branchement OVH) — SOURCE des dalles bathy
  // PC : « Serveur OVH (v2.0) » ou « Archive (Repli) » si serveur muet.
  const [tileSource, setTileSource] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.tilesSource()
      .then((r) => { if (alive) setTileSource(r.label); })
      .catch(() => { if (alive) setTileSource(null); });
    return () => { alive = false; };
  }, []);
  const [reportMark, setReportMark] = useState("");
  const [reportComment, setReportComment] = useState("");
  const [reportSending, setReportSending] = useState(false);

  const sendMarkReport = async () => {
    if (!route.route_id || reportSending) return;
    setReportSending(true);
    try {
      const r = await api.reportMarkIssue({
        route_id: route.route_id,
        mark_name: reportMark.trim() || undefined,
        comment: reportComment.trim() || undefined,
      });
      showToast("success", `Signalement envoyé (${r.report_id})`);
      setReportOpen(false);
      setReportMark("");
      setReportComment("");
    } catch {
      showToast("error", "Envoi impossible — réessayez.");
    } finally {
      setReportSending(false);
    }
  };

  const chart = useMemo(() => {
    if (!SHOW_DEPTH_PROFILE) return null;   // 27/08 — profil masqué (ordre armateur)
    const pts = route.depth_profile.filter((p) => p.depth_m != null);
    if (pts.length < 2) return null;
    const W = 1000; // viewBox — étiré à la largeur réelle
    const total = Math.max(1, route.distance_m);
    const maxDepth = Math.max(route.threshold_m + 1, ...pts.map((p) => p.depth_m as number));
    const x = (d: number) => (d / total) * W;
    const y = (depth: number) => (Math.min(depth, maxDepth) / maxDepth) * (CHART_H - 6) + 3;
    const lineStr = pts.map((p) => `${x(p.d_m).toFixed(1)},${y(p.depth_m as number).toFixed(1)}`).join(" ");
    const areaStr =
      `M0,0 L${lineStr.split(" ").join(" L")} L${W},0 Z`;
    const yThr = y(route.threshold_m);
    // 26/07 (demande armateur) — ZONE DANGEREUSE en rouge sur le profil :
    // portions où la hauteur d'eau (fond carte + marée mini) est sous le
    // seuil d'alerte 150 % (route.low_margin). Tap → centrage carte.
    let danger: { x0: number; x1: number; f0: number; f1: number; lat: number; lng: number; spanM: number; line: string } | null = null;
    const lm = route.low_margin;
    if (lm) {
      const tideH = route.tide?.height_start_m ?? route.tide_m ?? 0;
      const bad = pts.filter((p) => (p.depth_m as number) + tideH < lm.alert_at_m);
      if (bad.length) {
        const d0 = Math.min(...bad.map((p) => p.d_m));
        const d1 = Math.max(...bad.map((p) => p.d_m));
        const mid = bad[Math.floor(bad.length / 2)];
        danger = {
          x0: x(d0), x1: x(d1), f0: d0 / total, f1: d1 / total,
          lat: mid.lat, lng: mid.lng, spanM: Math.max(d1 - d0, 150),
          line: bad.map((p) => `${x(p.d_m).toFixed(1)},${y(p.depth_m as number).toFixed(1)}`).join(" "),
        };
      }
    }
    return { W, lineStr, areaStr, yThr, maxDepth, danger };
  }, [route]);

  return (
    <View style={styles.card} testID="route-card">
      <View style={styles.head}>
        <Ionicons name="navigate" size={16} color="#E5383B" />
        <Text style={styles.title}>{route.mode === "manual" ? "Route manuelle" : "Route conseillée"}</Text>
        {/* 08/09/2026 — infobulle « i » : décharge de responsabilité. */}
        <TouchableOpacity onPress={() => setInfoOpen((v) => !v)} hitSlop={8} testID="route-info-toggle">
          <Ionicons name="information-circle-outline" size={18} color="#A3CEF1" />
        </TouchableOpacity>
        <Text style={styles.dist} testID="route-distance">{fmtDist(route.distance_m, unit)}</Text>
        {onSave ? (
          <TouchableOpacity onPress={onSave} hitSlop={10} style={styles.close} testID="route-save">
            <Ionicons name="bookmark-outline" size={18} color="#2EC4B6" />
          </TouchableOpacity>
        ) : null}
        <TouchableOpacity onPress={onMinimize} hitSlop={10} style={styles.close} testID="route-minimize">
          <Ionicons name="chevron-down" size={20} color={theme.textMute} />
        </TouchableOpacity>
        <TouchableOpacity onPress={onClose} hitSlop={10} style={styles.close} testID="route-close">
          <Ionicons name="close" size={20} color={theme.textMute} />
        </TouchableOpacity>
      </View>

      {/* 09/09/2026 (V1.6) — CHRONO FINAL : temps de calcul définitif,
          bien visible juste sous le titre. */}
      {computeS != null ? (
        <Text style={styles.computeTime} testID="route-compute-time">
          {`Calculé en ${computeS.toFixed(1)} s`}
        </Text>
      ) : null}

      {infoOpen ? (
        <View style={styles.infoBox} testID="route-disclaimer">
          <Text style={styles.infoTxt}>
            Route CONSEILLÉE à titre indicatif : elle ne remplace ni les cartes
            marines officielles, ni la veille visuelle, ni les documents
            nautiques à jour. Le chef de bord reste seul responsable de sa
            navigation.
          </Text>
        </View>
      ) : null}

      {/* 08/09/2026 — TIRANT D'EAU sur le bandeau (+ besoin d'eau total). */}
      <View style={styles.tideRow} testID="route-draft">
        <Ionicons name="boat-outline" size={13} color="#48CAE4" />
        <Text style={styles.tideTxt}>
          {(draftM != null ? `Tirant d'eau : ${draftM.toFixed(1)} m · ` : "") +
            `besoin d'eau (tirant + marge) : ${route.threshold_m.toFixed(1)} m` +
            (route.min_depth_m != null ? ` · fond mini rencontré : ${route.min_depth_m.toFixed(1)} m` : "")}
        </Text>
      </View>

      {/* 08/09/2026 — MENU DÉPLIABLE : Enregistrer / Modifier / Partager /
          Supprimer (un seul bandeau, plus de popups multiples). */}
      <TouchableOpacity
        style={styles.menuToggle}
        onPress={() => setMenuOpen((v) => !v)}
        activeOpacity={0.8}
        testID="route-menu-toggle"
      >
        <Ionicons name={menuOpen ? "chevron-up" : "chevron-down"} size={14} color={theme.textMute} />
        <Text style={styles.menuToggleTxt}>Actions</Text>
      </TouchableOpacity>
      {menuOpen ? (
        <View style={styles.menuRow} testID="route-actions-menu">
          {onSave ? (
            <TouchableOpacity style={styles.menuBtn} onPress={onSave} testID="route-action-save">
              <Ionicons name="bookmark-outline" size={16} color="#2EC4B6" />
              <Text style={styles.menuBtnTxt}>Enregistrer</Text>
            </TouchableOpacity>
          ) : null}
          {onEdit ? (
            <TouchableOpacity style={styles.menuBtn} onPress={onEdit} testID="route-action-edit">
              <Ionicons name="create-outline" size={16} color="#48CAE4" />
              <Text style={styles.menuBtnTxt}>Modifier</Text>
            </TouchableOpacity>
          ) : null}
          {onShare ? (
            <TouchableOpacity style={styles.menuBtn} onPress={onShare} testID="route-action-share">
              <Ionicons name="share-social-outline" size={16} color="#A3CEF1" />
              <Text style={styles.menuBtnTxt}>Partager</Text>
            </TouchableOpacity>
          ) : null}
          {onDelete ? (
            <TouchableOpacity style={styles.menuBtn} onPress={onDelete} testID="route-action-delete">
              <Ionicons name="trash-outline" size={16} color="#E5383B" />
              <Text style={styles.menuBtnTxt}>Supprimer</Text>
            </TouchableOpacity>
          ) : null}
        </View>
      ) : null}

      {/* 31/07/2026 — ID PUBLIC de la route (support armateur) : chip
          copiable d'un tap. Communiqué au support pour consultation
          serveur (GET /api/routes/inspect/{id}).
          02/08/2026 — + MOTEUR (nom + ID stable) qui a produit ce tracé. */}
      {route.route_id || route.engine ? (
        <View style={styles.chipRow}>
          {route.route_id ? (
            <TouchableOpacity
              style={styles.idChip}
              onPress={async () => {
                await Clipboard.setStringAsync(route.route_id!);
                showToast("success", "ID de route copié");
              }}
              activeOpacity={0.7}
              hitSlop={6}
              testID="route-id-chip"
            >
              <Ionicons name="finger-print-outline" size={12} color={theme.textDim} />
              <Text style={styles.idChipText} numberOfLines={1}>{route.route_id}</Text>
              <Ionicons name="copy-outline" size={11} color={theme.textDim} />
            </TouchableOpacity>
          ) : null}
          {route.engine ? (
            <TouchableOpacity
              style={styles.idChip}
              onPress={async () => {
                await Clipboard.setStringAsync(route.engine!.id);
                showToast("success", `Moteur : ${route.engine!.name} (${route.engine!.id})`);
              }}
              activeOpacity={0.7}
              hitSlop={6}
              testID="route-engine-chip"
            >
              <Ionicons name="cog-outline" size={12} color={theme.textDim} />
              <Text style={styles.idChipText} numberOfLines={1}>
                {route.engine.name} · {route.engine.id}
              </Text>
            </TouchableOpacity>
          ) : null}
        </View>
      ) : null}

      {/* 04/09/2026 (ordre armateur) — SOURCE DES DALLES BATHY PC (preuve
          visuelle du branchement OVH ; les moteurs A-I restent sur la
          mosaïque SHOM embarquée, logique v8.1.0 INCHANGÉE). */}
      {tileSource ? (
        <View style={styles.tideRow} testID="route-tile-source">
          <Ionicons name="server-outline" size={13} color="#A3CEF1" />
          <Text style={[styles.tideTxt, { color: "#A3CEF1" }]}>
            {`Source : ${tileSource}`}
          </Text>
        </View>
      ) : null}

      {/* 27/08/2026 (demande armateur) — COORDONNÉES EXACTES du départ et de
          l'arrivée du tracé (tap = copier). Elles sont aussi conservées à
          l'enregistrement de la route (champs start/end en base). */}
      {route.waypoints.length >= 2 ? (
        <View style={styles.coordCol} testID="route-coords">
          {([
            ["Départ", route.waypoints[0], "flag-outline", "#80ED99"],
            ["Arrivée", route.waypoints[route.waypoints.length - 1], "location-outline", "#E5383B"],
          ] as const).map(([label, p, icon, color]) => (
            <TouchableOpacity
              key={label}
              style={styles.coordChip}
              onPress={async () => {
                await Clipboard.setStringAsync(`${p.lat.toFixed(6)}, ${p.lng.toFixed(6)}`);
                showToast("success", `${label} copié : ${p.lat.toFixed(6)}, ${p.lng.toFixed(6)}`);
              }}
              activeOpacity={0.7}
              hitSlop={6}
              testID={`route-coord-${label === "Départ" ? "start" : "end"}`}
            >
              <Ionicons name={icon} size={12} color={color} />
              <Text style={[styles.coordLabel, { color }]}>{label}</Text>
              <Text style={styles.coordText} numberOfLines={1}>
                {p.lat.toFixed(6)}, {p.lng.toFixed(6)}
              </Text>
              <Ionicons name="copy-outline" size={11} color={theme.textDim} />
            </TouchableOpacity>
          ))}
        </View>
      ) : null}

      {chart ? (
        <>
          <View
            style={styles.chartWrap}
            onLayout={(e) => setChartW(e.nativeEvent.layout.width)}
          >
            {chartW > 0 ? (
            <Svg width={chartW} height={CHART_H} viewBox={`0 0 ${chart.W} ${CHART_H}`} preserveAspectRatio="none">
              {/* Colonne d'eau (surface en haut, fond en bas du tracé) */}
              <Path d={chart.areaStr} fill="rgba(72,202,228,0.22)" />
              {/* 26/07 — bande rouge = section dangereuse (règle 150 %). */}
              {chart.danger ? (
                <Path
                  d={`M${chart.danger.x0},0 L${chart.danger.x1},0 L${chart.danger.x1},${CHART_H} L${chart.danger.x0},${CHART_H} Z`}
                  fill="rgba(229,56,59,0.28)"
                />
              ) : null}
              <Polyline
                points={chart.lineStr}
                fill="none"
                stroke="#48CAE4"
                strokeWidth={5}
                vectorEffect="non-scaling-stroke"
              />
              {chart.danger && chart.danger.line.includes(" ") ? (
                <Polyline
                  points={chart.danger.line}
                  fill="none"
                  stroke="#E5383B"
                  strokeWidth={6}
                  vectorEffect="non-scaling-stroke"
                />
              ) : null}
              {/* Seuil tirant d'eau + marge */}
              <Line
                x1={0} y1={chart.yThr} x2={chart.W} y2={chart.yThr}
                stroke="#E5383B" strokeWidth={3} strokeDasharray="10 8"
                vectorEffect="non-scaling-stroke"
              />
            </Svg>
            ) : null}
            {/* 26/07 — SENS DE LA ROUTE : départ à gauche, drapeau d'arrivée. */}
            <Text style={styles.chartStart} pointerEvents="none">Départ ▸</Text>
            <Text style={styles.chartFlag} pointerEvents="none">🏁</Text>
            {chart.danger && chartW > 0 && onFocusDanger ? (
              <TouchableOpacity
                style={[styles.dangerTap, {
                  left: Math.max(0, chartW * chart.danger.f0 - 8),
                  width: Math.max(28, chartW * (chart.danger.f1 - chart.danger.f0) + 16),
                }]}
                onPress={() => onFocusDanger(chart.danger!.lat, chart.danger!.lng, chart.danger!.spanM)}
                testID="route-chart-danger"
                accessibilityLabel="Voir la section dangereuse sur la carte"
              />
            ) : null}
          </View>
          {/* Légende HORS du conteneur du graphe (son overflow:hidden coupait
              « Seuil : x m » — bug visuel iter94). */}
          <View style={styles.chartLegend}>
            <Text style={styles.legendTxt} numberOfLines={1}>
              Fond mini : {route.min_depth_m != null ? `${route.min_depth_m.toFixed(1)} m` : "—"}
            </Text>
            {chart.danger ? (
              <Text style={[styles.legendTxt, { color: "#E5383B" }]} numberOfLines={1}>
                ■ zone dangereuse (tap = voir)
              </Text>
            ) : null}
            <Text style={[styles.legendTxt, { color: "#E5383B" }]} numberOfLines={1}>
              Seuil : {route.threshold_m.toFixed(1)} m
            </Text>
          </View>
        </>
      ) : null}

      {/* 27/07 (consigne armateur) — la hauteur utilisée est celle PRÉVUE
          ~30 min après le calcul (temps de mise en route) ; l'utilisateur
          doit re-vérifier à son heure de passage (ou actualiser la route). */}
      {route.tide ? (
        <View style={styles.tideRow} testID="route-tide-info">
          <Ionicons name="water" size={13} color="#48CAE4" />
          <Text style={styles.tideTxt}>
            Marée prévue à{" "}
            {new Date(route.tide.departure_ts * 1000).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
            {" "}(calcul +30 min) : +{(route.tide.height_start_m ?? route.tide.height_min_m).toFixed(1)} m
            {" · "}{route.tide.port} — mini ~+{route.tide.height_min_m.toFixed(1)} m sur{" "}
            {route.tide.window_h.toFixed(0)} h : vérifiez à votre heure de passage.
          </Text>
        </View>
      ) : null}

      {/* 26/07 (GO armateur) — fenêtre de marée SUFFISANTE : la route ne passe
          que grâce à la marée → jusqu'à quand ? / ira plus loin à partir de ? */}
      {route.tide_window ? (
        <View style={styles.tideRow} testID="route-tide-window">
          <Ionicons name="time" size={13} color="#F4A261" />
          <Text style={[styles.tideTxt, { color: "#F4A261" }]}>
            Passable tant que la marée ≥ +{route.tide_window.required_m.toFixed(1)} m
            {route.tide_window.ok_until_ts
              ? ` — jusqu'à ~${fmtTideTs(route.tide_window.ok_until_ts)}.`
              : " — toute la journée (≥ 24 h)."}
          </Text>
        </View>
      ) : null}
      {route.tide_better ? (
        <View style={styles.tideRow} testID="route-tide-better">
          <Ionicons name="trending-up" size={13} color="#80ED99" />
          <Text style={[styles.tideTxt, { color: "#80ED99" }]}>
            Ira plus loin (arrivée à ~{(route.tide_better.offset_m / 1000).toFixed(1)} km
            de la destination) à partir de ~{fmtTideTs(route.tide_better.ts)} (marée ≥ +
            {route.tide_better.required_m.toFixed(1)} m) : actualisez la route à ce moment-là.
          </Text>
        </View>
      ) : null}

      {/* 28/07 (GO armateur) — MINI-GRAPHE DE MARÉE 24 h : la fenêtre de tir
          (zone passable soulignée en vert) se lit d'un coup d'œil. */}
      {route.tide && route.waypoints.length ? (
        <TideMiniGraph
          lat={route.waypoints[route.waypoints.length - 1].lat}
          lng={route.waypoints[route.waypoints.length - 1].lng}
          requiredM={route.tide_window ? route.tide_window.required_m : null}
        />
      ) : null}

      {/* 03/08/2026 (Moteur C) — SENS DE CALCUL + marge appliquée : l'armateur
          doit pouvoir vérifier d'un coup d'œil que le tracé a bien été calculé
          dans le sens conventionnel (mer → terre) et avec quelle marge. */}
      {route.engine_rules ? (
        <View style={styles.tideRow} testID="route-engine-rules">
          <Ionicons name="git-compare" size={13} color="#A3CEF1" />
          <Text style={[styles.tideTxt, { color: "#A3CEF1" }]}>
            {`Calcul dans le sens conventionnel (mer → terre)${route.engine_rules.computed_reversed ? ", tracé retourné pour votre sens de parcours" : ""}`}
            {route.lateral_margin_used_m != null
              ? ` · marge latérale ${Math.round(route.lateral_margin_used_m)} m`
              : ""}
          </Text>
        </View>
      ) : null}

      {/* 03/08/2026 (Moteur C — règles armateur) — CONFORMITÉ DU TRACÉ :
          balises laissées du mauvais côté et tronçons dont la marge latérale
          est sous 20 m. Bloc dédié EN ROUGE, au-dessus des avertissements
          génériques, pour que ces deux règles ne se noient pas dans la liste. */}
      {route.wrong_side_marks?.length ? (
        <View style={styles.ruleBox} testID="route-wrong-side">
          <View style={styles.ruleHead}>
            <Ionicons name="alert-circle" size={14} color="#FF6B6B" />
            <Text style={styles.ruleTitle}>Balisage non respecté</Text>
          </View>
          {route.wrong_side_marks.map((m) => (
            <Text key={`${m.name}-${m.dist_m}`} style={styles.ruleTxt}>
              {`« ${m.name} » (${m.kind === "cardinal" ? "cardinale" : m.category === "port" ? "rouge" : "verte"}) doit être laissée ${m.side_required} — passage à ~${Math.round(m.dist_m)} m`}
            </Text>
          ))}
        </View>
      ) : null}
      {route.endpoint_cardinals?.length ? (
        <View style={styles.ruleBox} testID="route-endpoint-cardinals">
          <View style={styles.ruleHead}>
            <Ionicons name="warning" size={14} color="#FF6B6B" />
            <Text style={styles.ruleTitle}>Cardinale — secteur dangereux</Text>
          </View>
          {route.endpoint_cardinals.map((m) => (
            <Text key={`ec-${m.name}-${m.dist_m}`} style={styles.ruleTxt}>
              {`Votre départ ou votre arrivée est du côté dangereux de « ${m.name} » (à laisser ${m.side_required}) — sortez du secteur à vue.`}
            </Text>
          ))}
        </View>
      ) : null}
      {route.low_margin_legs?.length ? (
        <View style={styles.ruleBox} testID="route-low-margin-legs">
          <View style={styles.ruleHead}>
            <Ionicons name="resize" size={14} color="#FF6B6B" />
            <Text style={styles.ruleTitle}>Marge latérale &lt; 20 m</Text>
          </View>
          <Text style={styles.ruleTxt}>
            {`${route.low_margin_legs.length} tronçon${route.low_margin_legs.length > 1 ? "s" : ""} en ROUGE : impossible de garder 20 m de part et d'autre du tracé — passage à vue, vitesse réduite.`}
          </Text>
        </View>
      ) : null}
      {route.side_fixed?.length ? (
        <View style={styles.okRow} testID="route-side-fixed">
          <Ionicons name="checkmark-circle" size={13} color="#80ED99" />
          <Text style={styles.okTxt}>
            {`Côté de passage corrigé pour : ${route.side_fixed.join(", ")}.`}
          </Text>
        </View>
      ) : null}

      {route.warnings.map((w) => (
        <View key={w} style={styles.warnRow}>
          <Ionicons name="warning" size={13} color="#F4A261" />
          <Text style={styles.warnTxt}>{w}</Text>
        </View>
      ))}
      {/* 09/09/2026 (V1.6, ordre armateur) — l'écran d'accusé de lecture
          « Ok, j'ai compris » est SUPPRIMÉ : accès DIRECT au suivi, avec le
          bouton vert « Suivre cette route » et « Enregistrer cette route ». */}
      {onNavigate ? (
        <TouchableOpacity
          style={styles.followBtn}
          onPress={onNavigate}
          activeOpacity={0.85}
          testID="route-follow-start"
        >
          <Ionicons name="play" size={16} color="#04121F" />
          <Text style={styles.followTxt}>Suivre cette route</Text>
        </TouchableOpacity>
      ) : null}
      {onSave ? (
        <TouchableOpacity
          style={styles.saveBtn}
          onPress={onSave}
          activeOpacity={0.85}
          testID="route-save-big"
        >
          <Ionicons name="bookmark" size={15} color="#2EC4B6" />
          <Text style={styles.saveBtnTxt}>Enregistrer cette route</Text>
        </TouchableOpacity>
      ) : null}
      {/* 02/08/2026 (demande armateur) — A/B TESTING de moteurs : recalcule
          cette route avec un autre moteur et superpose les deux tracés. */}
      {onCompareEngine ? (
        <TouchableOpacity
          style={styles.compareBtn}
          onPress={onCompareEngine}
          activeOpacity={0.85}
          testID="route-compare-open"
        >
          <Ionicons name="git-compare-outline" size={15} color="#48CAE4" />
          <Text style={styles.compareTxt}>Recalculer avec un autre moteur</Text>
          <Ionicons name="chevron-forward" size={15} color={theme.textMute} />
        </TouchableOpacity>
      ) : null}
      {/* 14/08/2026 (demande armateur) — SIGNALER UN BALISAGE NON RESPECTÉ :
          envoie automatiquement l'ID de route + la balise concernée au
          support (les balises mauvais côté déjà détectées sont jointes). */}
      {route.route_id ? (
        <TouchableOpacity
          style={styles.reportBtn}
          onPress={() => setReportOpen(true)}
          activeOpacity={0.85}
          testID="route-mark-report-open"
        >
          <Ionicons name="flag-outline" size={15} color="#F4A261" />
          <Text style={styles.reportTxt}>Signaler un balisage non respecté</Text>
          <Ionicons name="chevron-forward" size={15} color={theme.textMute} />
        </TouchableOpacity>
      ) : null}
      <Modal visible={reportOpen} transparent animationType="fade"
        onRequestClose={() => setReportOpen(false)}>
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.reportOverlay}
        >
          <View style={styles.reportBox} testID="route-mark-report-modal">
            <View style={styles.reportHead}>
              <Ionicons name="flag" size={16} color="#F4A261" />
              <Text style={styles.reportTitle}>Balisage non respecté</Text>
              <TouchableOpacity onPress={() => setReportOpen(false)} hitSlop={10}
                testID="route-mark-report-close">
                <Ionicons name="close" size={20} color={theme.textMute} />
              </TouchableOpacity>
            </View>
            <Text style={styles.reportHint}>
              {`Route ${route.route_id} — l'ID, le moteur et les balises déjà détectées seront joints automatiquement.`}
            </Text>
            <TextInput
              style={styles.reportInput}
              placeholder="Balise concernée (ex. N°12, Truie d'Arradon)"
              placeholderTextColor={theme.textMute}
              value={reportMark}
              onChangeText={setReportMark}
              testID="route-mark-report-mark"
            />
            <TextInput
              style={[styles.reportInput, styles.reportInputMulti]}
              placeholder="Commentaire (facultatif)"
              placeholderTextColor={theme.textMute}
              value={reportComment}
              onChangeText={setReportComment}
              multiline
              testID="route-mark-report-comment"
            />
            <TouchableOpacity
              style={[styles.reportSend, reportSending ? { opacity: 0.6 } : null]}
              onPress={sendMarkReport}
              disabled={reportSending}
              activeOpacity={0.85}
              testID="route-mark-report-send"
            >
              {reportSending
                ? <ActivityIndicator size="small" color="#0B132B" />
                : <Ionicons name="send" size={15} color="#0B132B" />}
              <Text style={styles.reportSendTxt}>Envoyer le signalement</Text>
            </TouchableOpacity>
          </View>
        </KeyboardAvoidingView>
      </Modal>
      <Text style={styles.disclaimer}>
        {"Astuce : appui long sur le tracé pour déplacer le waypoint le plus proche (recalcul automatique)."}
      </Text>
      <Text style={styles.disclaimer}>
        {route.tide
          ? "Profondeurs SHOM + marée Open-Meteo (approchée, non officielle) — vérifiez la marée sur zone."
          : "Profondeurs SHOM au zéro hydrographique (marée basse) — aide à la navigation, ne remplace pas les cartes officielles."}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: "rgba(11,19,43,0.94)",
    borderRadius: radii.md,
    borderWidth: 1,
    borderColor: theme.border,
    padding: spacing.sm,
    gap: 6,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { color: theme.text, fontSize: 14, fontWeight: "900" },
  dist: { color: "#48CAE4", fontSize: 13, fontWeight: "800", flex: 1, textAlign: "right" },
  close: { padding: 2, zIndex: 2 },
  chipRow: {
    flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap",
  },
  compareBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    minHeight: 44, paddingHorizontal: 12, borderRadius: radii.md,
    borderWidth: 1, borderColor: "rgba(72,202,228,0.35)",
    backgroundColor: "rgba(72,202,228,0.08)", marginTop: 8,
  },
  compareTxt: { flex: 1, color: "#48CAE4", fontSize: 12.5, fontWeight: "800" },
  // 14/08 — signalement balisage non respecté (bouton + modal).
  reportBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    minHeight: 44, paddingHorizontal: 12, borderRadius: radii.md,
    borderWidth: 1, borderColor: "rgba(244,162,97,0.35)",
    backgroundColor: "rgba(244,162,97,0.08)",
  },
  reportTxt: { flex: 1, color: "#F4A261", fontSize: 12.5, fontWeight: "800" },
  reportOverlay: {
    flex: 1, backgroundColor: "rgba(4,10,22,0.72)",
    justifyContent: "center", padding: spacing.lg,
  },
  reportBox: {
    backgroundColor: "rgba(11,19,43,0.98)", borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border, padding: spacing.md, gap: 10,
  },
  reportHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  reportTitle: { flex: 1, color: theme.text, fontSize: 14, fontWeight: "900" },
  reportHint: { color: theme.textDim, fontSize: 11, lineHeight: 15 },
  reportInput: {
    borderWidth: 1, borderColor: theme.border, borderRadius: radii.sm,
    color: theme.text, paddingHorizontal: 10, paddingVertical: 10,
    fontSize: 13, minHeight: 44, backgroundColor: "rgba(255,255,255,0.04)",
  },
  reportInputMulti: { minHeight: 64, textAlignVertical: "top" },
  reportSend: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 8, backgroundColor: "#F4A261", borderRadius: radii.md,
    paddingVertical: 11, minHeight: 44,
  },
  reportSendTxt: { color: "#0B132B", fontWeight: "900", fontSize: 13.5 },
  idChip: {
    flexDirection: "row", alignItems: "center", gap: 5,
    alignSelf: "flex-start", paddingVertical: 3, paddingHorizontal: 8,
    backgroundColor: "rgba(72,202,228,0.10)",
    borderWidth: 1, borderColor: "rgba(72,202,228,0.25)",
    borderRadius: radii.sm,
    maxWidth: "62%",
  },
  idChipText: {
    color: theme.textDim, fontSize: 10.5, fontWeight: "700",
    fontVariant: ["tabular-nums"], letterSpacing: 0.3,
  },
  // 27/08 — coordonnées exactes départ/arrivée (tap = copier).
  coordCol: { gap: 4 },
  coordChip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    alignSelf: "stretch", paddingVertical: 4, paddingHorizontal: 8,
    backgroundColor: "rgba(255,255,255,0.04)",
    borderWidth: 1, borderColor: theme.border, borderRadius: radii.sm,
  },
  coordLabel: { fontSize: 10.5, fontWeight: "900", width: 46 },
  coordText: {
    flex: 1, color: theme.textDim, fontSize: 11, fontWeight: "700",
    fontVariant: ["tabular-nums"], letterSpacing: 0.3,
  },
  chartWrap: {
    backgroundColor: "rgba(255,255,255,0.05)",
    borderRadius: radii.sm,
    overflow: "hidden",
    alignSelf: "stretch",
    height: CHART_H,
  },
  chartLegend: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
  },
  legendTxt: { color: theme.textDim, fontSize: 10, fontWeight: "700" },
  // 26/07 — sens de la route + zone dangereuse tappable sur le profil.
  chartStart: {
    position: "absolute", left: 6, top: 3, color: "rgba(232,236,251,0.75)",
    fontSize: 9, fontWeight: "800",
  },
  chartFlag: { position: "absolute", right: 4, top: 1, fontSize: 15 },
  dangerTap: { position: "absolute", top: 0, bottom: 0, minWidth: 28 },
  warnRow: { flexDirection: "row", alignItems: "flex-start", gap: 6 },
  warnTxt: { color: "#F4A261", fontSize: 11, flex: 1, lineHeight: 15 },
  // 03/08/2026 (Moteur C) — bloc « règle non respectée » (balisage / marge).
  ruleBox: {
    backgroundColor: "rgba(255,23,68,0.10)",
    borderWidth: 1, borderColor: "rgba(255,107,107,0.45)",
    borderRadius: radii.sm, padding: spacing.sm, gap: 4,
  },
  ruleHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  ruleTitle: { color: "#FF6B6B", fontSize: 11, fontWeight: "900", letterSpacing: 0.3 },
  ruleTxt: { color: "#FFD1D1", fontSize: 11, lineHeight: 15 },
  okRow: { flexDirection: "row", alignItems: "flex-start", gap: 6 },
  okTxt: { color: "#80ED99", fontSize: 11, flex: 1, lineHeight: 15 },
  tideRow: { flexDirection: "row", alignItems: "flex-start", gap: 6 },
  tideTxt: { color: "#48CAE4", fontSize: 11, flex: 1, lineHeight: 15, fontWeight: "700" },
  // 08/09/2026 — infobulle « i » (décharge de responsabilité).
  infoBox: {
    backgroundColor: "rgba(163,206,241,0.10)", borderRadius: radii.sm,
    borderWidth: 1, borderColor: "rgba(163,206,241,0.35)",
    paddingHorizontal: 10, paddingVertical: 8, marginBottom: 6,
  },
  infoTxt: { color: "#A3CEF1", fontSize: 11, lineHeight: 15 },
  // 08/09/2026 — menu dépliable Enregistrer/Modifier/Partager/Supprimer.
  menuToggle: {
    flexDirection: "row", alignItems: "center", gap: 4,
    alignSelf: "flex-start", paddingVertical: 4, paddingHorizontal: 2,
  },
  menuToggleTxt: { color: theme.textMute, fontSize: 12, fontWeight: "700" },
  menuRow: {
    flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 6,
  },
  menuBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, minHeight: 40,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: radii.sm,
    backgroundColor: "rgba(255,255,255,0.06)", borderWidth: 1,
    borderColor: "rgba(255,255,255,0.14)",
  },
  menuBtnTxt: { color: theme.text, fontSize: 12, fontWeight: "700" },
  followBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: "#2EC4B6", borderRadius: radii.md, paddingVertical: 10, minHeight: 44,
  },
  followTxt: { color: "#04121F", fontWeight: "900", fontSize: 14 },
  // 09/09/2026 (V1.6) — bouton « Enregistrer cette route » sous le suivi.
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    borderRadius: radii.md, paddingVertical: 9, minHeight: 44, marginTop: 8,
    borderWidth: 1.5, borderColor: "#2EC4B6",
  },
  saveBtnTxt: { color: "#2EC4B6", fontWeight: "900", fontSize: 13 },
  // 09/09/2026 (V1.6) — chrono final sous le titre.
  computeTime: { color: "#48CAE4", fontSize: 12, fontWeight: "800", marginBottom: 6 },
  disclaimer: { color: theme.textMute, fontSize: 9, lineHeight: 12 },
});
