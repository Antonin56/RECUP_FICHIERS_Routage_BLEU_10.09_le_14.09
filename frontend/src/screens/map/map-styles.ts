// SignalMar — Styles de l'écran Carte (extraits de app/(tabs)/map.tsx le
// 20/07/2026, refactor N0 — déplacement PUR, aucun changement fonctionnel).
import { StyleSheet } from "react-native";

import { theme, spacing, radii } from "@/src/lib/theme";

export const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  topOverlay: { position: "absolute", top: 0, left: 0, right: 0, gap: spacing.sm, paddingTop: spacing.sm },
  // Paysage : couloir libre à droite (44 px d'icône + marge) pour que les
  // pills ET les bandeaux ne passent JAMAIS sous la colonne de FABs.
  topOverlayLandscape: { paddingRight: 44 + spacing.md + spacing.sm },
  topRow: {
    flexDirection: "row", justifyContent: "space-between", gap: spacing.sm,
    paddingHorizontal: spacing.md,
  },
  badge: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(11,19,43,0.85)", paddingHorizontal: 10, paddingVertical: 8,
    borderRadius: radii.pill, borderWidth: 1, borderColor: theme.border,
    flexShrink: 1,
  },
  badgeText: {
    color: theme.text, fontWeight: "700", fontSize: 11,
    fontVariant: ["tabular-nums"], flexShrink: 1,
  },
  // Compteur de vitesse — pill compacte de la barre du haut (10/07).
  topSpeedPill: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "rgba(11,19,43,0.85)", paddingHorizontal: 8, paddingVertical: 8,
    borderRadius: radii.pill, borderWidth: 1, borderColor: theme.border,
  },
  // 24/07 soir — refresh déplacé à côté des coordonnées (petit bouton rond).
  topRefreshBtn: {
    width: 30, height: 30, borderRadius: 15,
    backgroundColor: "rgba(11,19,43,0.85)",
    borderWidth: 1, borderColor: theme.border,
    alignItems: "center", justifyContent: "center",
  },
  topSpeedText: {
    color: theme.text, fontWeight: "800", fontSize: 11,
    fontVariant: ["tabular-nums"],
  },
  demoBadge: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(244,162,97,0.18)",
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radii.pill, borderWidth: 1, borderColor: theme.warning,
  },
  demoText: { color: theme.warning, fontWeight: "800", fontSize: 12 },
  radiusBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "rgba(11,19,43,0.85)", paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radii.pill, borderWidth: 1, borderColor: theme.border,
  },
  radiusBtnText: { color: theme.primary, fontWeight: "800", fontSize: 12 },
  // Phase 3c — bell button (in-app notifications). Compact circular pill next
  // to the radius button. Shows a red badge with the unread count.
  bellBtn: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: "rgba(11,19,43,0.85)",
    borderWidth: 1, borderColor: theme.border,
    alignItems: "center", justifyContent: "center",
    position: "relative",
  },
  bellBadge: {
    position: "absolute", top: -4, right: -4,
    minWidth: 18, height: 18, borderRadius: 9,
    backgroundColor: "#E63946",
    alignItems: "center", justifyContent: "center",
    paddingHorizontal: 4,
    borderWidth: 1.5, borderColor: theme.bg,
  },
  bellBadgeText: {
    color: "#FFFFFF", fontWeight: "900", fontSize: 10,
    letterSpacing: 0,
  },
  // Phase 3c — welcome banner (one-shot, first mount of the session).
  welcomeCard: {
    marginTop: spacing.sm,
    // 23/07/2026 (retour armateur) — couloir libre à droite : le bandeau ne
    // doit JAMAIS passer sous la colonne de zoom fixe (44 px + marges).
    marginLeft: spacing.md,
    marginRight: 44 + spacing.md + spacing.sm,
    paddingHorizontal: spacing.sm, paddingVertical: 10,
    borderRadius: radii.md,
    backgroundColor: "rgba(28, 37, 65, 0.96)",
    borderWidth: 1, borderColor: theme.primary,
    flexDirection: "row", alignItems: "center", gap: 10,
    shadowColor: "#000",
    shadowOpacity: 0.35,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 4 },
    elevation: 8,
  },
  welcomeIcon: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
  },
  welcomeTitle: { color: theme.text, fontWeight: "900", fontSize: 13 },
  welcomeText: { color: theme.textDim, fontSize: 12, marginTop: 2, lineHeight: 15 },
  welcomeBtn: {
    backgroundColor: theme.primary,
    paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: radii.pill,
    minHeight: 36,
    alignItems: "center", justifyContent: "center",
  },
  welcomeBtnText: { color: theme.bg, fontWeight: "900", fontSize: 12 },
  // Bascule auto Vigie ⇄ Navigation — bannière (mêmes textes/boutons que la
  // welcome card, accent orange pour la distinguer).
  autoSwitchCard: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: "#F4A261",
    padding: spacing.sm, marginTop: spacing.sm,
    // 23/07/2026 — couloir libre à droite (colonne zoom 44 px + marges).
    marginRight: 44 + spacing.md + spacing.sm,
  },
  autoSwitchIcon: {
    width: 32, height: 32, borderRadius: 16, backgroundColor: "#F4A261",
    alignItems: "center", justifyContent: "center",
  },
  welcomeClose: {
    width: 22, height: 22, borderRadius: 11,
    alignItems: "center", justifyContent: "center",
    marginLeft: 2,
  },
  filterRow: { height: 48, justifyContent: "center" },
  chip: {
    flexShrink: 0, flexDirection: "row", alignItems: "center", gap: 6,
    height: 36, paddingHorizontal: 14, borderRadius: radii.pill,
    backgroundColor: "rgba(11,19,43,0.92)", borderWidth: 1, borderColor: theme.border,
  },
  chipText: { color: theme.text, fontWeight: "800", fontSize: 12 },
  permBox: {
    flexDirection: "row", gap: 8, alignItems: "center", marginHorizontal: spacing.md,
    backgroundColor: "rgba(244,162,97,0.15)", borderColor: theme.warning, borderWidth: 1,
    padding: spacing.sm, borderRadius: radii.md,
  },
  permText: { color: theme.text, flex: 1, fontSize: 12 },
  // 17/07 (test armateur) — le stack s'étend sur toute la largeur : bouton
  // « Signaler » CENTRÉ horizontalement, colonne d'icônes ancrée à droite.
  fabStack: { position: "absolute", left: 0, right: 0, gap: spacing.sm },
  // 12/07 — Signaler à GAUCHE de la colonne d'icônes ; icônes légèrement
  // réduites (44 px) pour que la pile tienne aussi en mode paysage.
  fabRow: { flexDirection: "row", alignItems: "flex-end", justifyContent: "center" },
  // Colonne d'icônes en ABSOLU (bas-droite) : le Signaler centré ne bouge
  // pas, la colonne empile ses boutons vers le haut depuis le même bas.
  fabCol: { position: "absolute", right: spacing.md, bottom: 0, alignItems: "center", gap: spacing.sm },
  // Boutons zoom → composant DraggableZoomButtons (13/07/2026).
  // Loupe ID COURT — bas gauche, discret (12/07/2026).
  searchFab: {
    position: "absolute", left: spacing.md,
    width: 44, height: 44, borderRadius: 22,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: theme.borderStrong,
    shadowColor: "#000", shadowOpacity: 0.3, shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 }, elevation: 4,
  },
  searchBackdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center", justifyContent: "center", padding: spacing.lg,
  },
  searchSheet: {
    width: "100%", maxWidth: 420, backgroundColor: theme.bg2,
    borderRadius: radii.lg, padding: spacing.lg, gap: spacing.sm,
    borderWidth: 1, borderColor: theme.border,
  },
  searchTitleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  searchTitle: { color: theme.text, fontWeight: "800", fontSize: 16 },
  searchHint: { color: theme.textDim, fontSize: 13 },
  searchInput: {
    backgroundColor: theme.bg, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    color: theme.text, fontWeight: "800", fontSize: 18, letterSpacing: 2,
    paddingHorizontal: spacing.md, paddingVertical: 12, textAlign: "center",
  },
  searchErr: { color: theme.danger, fontSize: 13, fontWeight: "600" },
  searchBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: theme.primary, borderRadius: radii.md, paddingVertical: 12,
  },
  searchBtnTxt: { color: theme.bg, fontWeight: "900", fontSize: 15 },
  locBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.bg2,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.border,
  },
  // Phase E.5 — Manual refresh button; sits between nav toggle and locate.
  refreshBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.bg2,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.border,
  },
  // 19/07/2026 — PROTOTYPE bathymétrie SHOM (toggle goutte d'eau).
  bathyBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.bg2,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.border,
  },
  bathyBtnOn: {
    borderColor: "#48CAE4",
    shadowColor: "#48CAE4", shadowOpacity: 0.5, shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 }, elevation: 4,
  },
  // 24/07/2026 — compas de mesure actif (halo ambré assorti aux épingles).
  measureBtnOn: {
    borderColor: "#FFD166",
    shadowColor: "#FFD166", shadowOpacity: 0.5, shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 }, elevation: 4,
  },
  // 24/07/2026 — fiche hauteur d'eau au point cliqué.
  waterCardWrap: {
    position: "absolute", left: 0, right: 0, bottom: 98,
    alignItems: "center", zIndex: 30,
  },
  waterCard: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "rgba(13,27,42,0.95)",
    borderColor: "rgba(72,202,228,0.5)", borderWidth: 1,
    borderRadius: 12, paddingHorizontal: 12, paddingVertical: 8,
    maxWidth: "92%",
  },
  waterTxt: { color: theme.text, fontSize: 12.5, fontWeight: "700", flexShrink: 1 },
  // 24/07 soir — bandeau de suivi de route RÉDUIT (docké en bas).
  navMiniWrap: {
    position: "absolute", left: 8, right: 8, bottom: 6, zIndex: 40,
  },
  // 24/07/2026 — acceptation du risque (route douteuse, tronçon rouge).
  riskTitle: { color: "#FF6B6B", fontSize: 16, fontWeight: "900", marginBottom: 8 },
  riskMsg: { color: theme.text, fontSize: 13, lineHeight: 19, marginBottom: 14 },
  // 26/07/2026 — bannière d'écart de route persistante (remplace le toast).
  devWrap: { position: "absolute", left: 12, right: 12, zIndex: 60 },
  devCard: { borderColor: "#E5383B" },
  devBtnRow: { flexDirection: "row", gap: 8 },
  devBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    flex: 1, backgroundColor: "#E5383B", borderRadius: 10,
    paddingVertical: 9, minHeight: 40,
  },
  devBtnMuted: { backgroundColor: "rgba(255,255,255,0.10)" },
  devBtnTxt: { color: "#fff", fontSize: 12, fontWeight: "800" },
  devBtnGhost: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    flex: 1, backgroundColor: "rgba(255,255,255,0.08)", borderRadius: 10,
    paddingVertical: 9, minHeight: 40,
    borderWidth: 1, borderColor: "rgba(255,255,255,0.22)",
  },
  devBtnGhostTxt: { color: theme.text, fontSize: 12, fontWeight: "700" },
  devPill: {
    alignSelf: "center", flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(183,28,28,0.95)", borderRadius: 999,
    paddingHorizontal: 14, paddingVertical: 8, minHeight: 36,
    borderWidth: 1, borderColor: "#E5383B",
  },
  devPillTxt: { color: "#fff", fontSize: 12, fontWeight: "900" },
  // 29/07/2026 — pastille « Précision GPS réduite » (avertissement simple).
  gpsPoorPill: {
    alignSelf: "center", flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(244,162,97,0.95)", borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 6, minHeight: 28,
  },
  gpsPoorTxt: { color: "#0B132B", fontSize: 11, fontWeight: "900" },
  // 26/07 — bouton retour au profil (route ouverte depuis « Mes routes »).
  backProfileBtn: {
    position: "absolute", left: 12, zIndex: 70,
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "rgba(13,27,42,0.95)", borderWidth: 1, borderColor: theme.border,
    borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8, minHeight: 40,
  },
  backProfileTxt: { color: theme.text, fontSize: 13, fontWeight: "800" },
  riskAcceptBtn: {
    backgroundColor: "#E5383B", borderRadius: 12, paddingVertical: 12,
    alignItems: "center", marginBottom: 8, minHeight: 44, justifyContent: "center",
  },
  riskAcceptTxt: { color: "#fff", fontWeight: "900", fontSize: 14 },
  riskCancelBtn: {
    borderColor: theme.line, borderWidth: 1, borderRadius: 12,
    paddingVertical: 11, alignItems: "center", minHeight: 44, justifyContent: "center",
  },
  riskCancelTxt: { color: theme.textMute, fontWeight: "700", fontSize: 14 },
  // 23/07/2026 — ALARME DE MOUILLAGE : bouton ancre + bannière d'alarme.
  anchorBtnOn: {
    borderColor: "#2EC4B6",
    shadowColor: "#2EC4B6", shadowOpacity: 0.5, shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 }, elevation: 4,
  },
  anchorBtnAlarm: {
    borderColor: "#E5383B",
    shadowColor: "#E5383B", shadowOpacity: 0.6, shadowRadius: 10,
    shadowOffset: { width: 0, height: 0 }, elevation: 6,
  },
  anchorAlarmCard: {
    backgroundColor: "rgba(94,17,20,0.96)",
    borderRadius: radii.md, borderWidth: 1.5, borderColor: "#E5383B",
    padding: spacing.md, gap: spacing.sm,
  },
  anchorAlarmHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  anchorAlarmTitle: { color: "#FFD3D5", fontSize: 14, fontWeight: "900", flex: 1 },
  anchorAlarmTxt: { color: "#FFECEC", fontSize: 12, fontWeight: "700", lineHeight: 17 },
  anchorAlarmBtnRow: { flexDirection: "row", gap: spacing.sm },
  anchorAlarmBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    borderRadius: radii.md, paddingVertical: 10, minHeight: 44,
  },
  anchorStatusRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: theme.bg, borderRadius: radii.md, borderWidth: 1,
    borderColor: theme.border, padding: spacing.sm, marginBottom: spacing.sm,
  },
  anchorStatusTxt: { color: theme.textDim, fontSize: 12, fontWeight: "700", flex: 1, lineHeight: 16 },
  anchorActionBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    borderRadius: radii.md, paddingVertical: 12, minHeight: 48, marginTop: spacing.sm,
  },
  anchorActionTxt: { color: "#04121F", fontWeight: "900", fontSize: 15 },
  // 23/07/2026 — boutons zoom FIXES haut-droite (sous le bouton notifs).
  zoomStackFixed: {
    position: "absolute",
    right: spacing.md,
    width: 44,
    borderRadius: radii.md,
    backgroundColor: "rgba(11,19,43,0.92)",
    borderWidth: 1,
    borderColor: theme.border,
    overflow: "hidden",
    shadowColor: "#000", shadowOpacity: 0.35, shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 }, elevation: 5,
  },
  zoomBtnFixed: { width: 44, height: 44, alignItems: "center", justifyContent: "center" },
  zoomSepFixed: { height: 1, backgroundColor: theme.border },
  modalBackdropFill: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  // 20/07 (N0) — curseur d'opacité bathymétrie avec aperçu temps réel.
  bathySliderHead: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: spacing.md,
  },
  bathySliderLabel: { color: theme.textDim, fontSize: 13, fontWeight: "700" },
  bathySliderValue: { color: "#48CAE4", fontSize: 14, fontWeight: "900" },
  // 20/07 (N0) — menu appui long « Signaler ici / Naviguer ici ».
  longPressCoords: {
    color: theme.textDim, fontSize: 12, fontWeight: "700",
    marginTop: 4, marginBottom: spacing.xs,
  },
  longPressRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 12, paddingHorizontal: 10,
    borderRadius: radii.md, borderWidth: 1, borderColor: theme.border,
    backgroundColor: theme.bg, marginTop: spacing.sm,
  },
  longPressLabel: { color: theme.text, fontSize: 15, fontWeight: "800" },
  // N1 (20/07) — route sûre : conteneur de la RouteCard + pill de calcul.
  routeCardWrap: {
    // right:72 → ne passe pas SOUS la colonne de boutons de droite (iter94).
    position: "absolute", left: spacing.md, right: 72, bottom: 128,
  },
  routeBusyPill: {
    flexDirection: "row", alignItems: "center", gap: 8, alignSelf: "center",
    backgroundColor: "rgba(11,19,43,0.92)", borderWidth: 1, borderColor: theme.border,
    borderRadius: radii.pill, paddingHorizontal: 14, paddingVertical: 8,
  },
  routeBusyTxt: { color: theme.text, fontSize: 12, fontWeight: "700" },
  // 08/09/2026 — bouton « ARRÊTER LE CALCUL » sous le chrono.
  routeStopBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, alignSelf: "center", marginTop: 8, minHeight: 44,
    paddingHorizontal: 18, paddingVertical: 10, borderRadius: 22,
    backgroundColor: "#B0231F", borderWidth: 1, borderColor: "#E5383B",
  },
  routeStopTxt: { color: "#fff", fontSize: 13, fontWeight: "800", letterSpacing: 0.5 },
  // 23/07 — carte PERSISTANTE « Passage impossible » (réglage en cause +
  // bouton Mon bateau). Remplace le toast de 3,5 s, trop court.
  blockedCard: {
    backgroundColor: "rgba(11,19,43,0.96)", borderWidth: 1,
    borderColor: "rgba(229,56,59,0.55)", borderRadius: radii.md,
    padding: spacing.md, gap: spacing.sm,
  },
  blockedHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  blockedTitle: { color: theme.danger, fontSize: 15, fontWeight: "900", flex: 1 },
  blockedMsg: { color: theme.text, fontSize: 12, lineHeight: 17 },
  blockedBtnRow: { flexDirection: "row", justifyContent: "flex-end", gap: 8, flexWrap: "wrap" },
  blockedBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: theme.primary, borderRadius: radii.pill,
    paddingHorizontal: 14, paddingVertical: 10, minHeight: 44,
  },
  blockedBtnTxt: { color: theme.bg, fontSize: 13, fontWeight: "800" },
  // 02/08/2026 — variante secondaire (bandeau « calcul interrompu »).
  blockedBtnAlt: {
    backgroundColor: "transparent",
    borderWidth: 1, borderColor: "rgba(72,202,228,0.45)",
  },
  blockedBtnAltTxt: { color: "#48CAE4", fontSize: 13, fontWeight: "800" },
  // 21/07 — mini-pill de la route réduite.
  routeMinPill: {
    flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-start",
    backgroundColor: "rgba(11,19,43,0.92)", borderWidth: 1, borderColor: theme.border,
    borderRadius: radii.pill, paddingHorizontal: 12, paddingVertical: 8,
  },
  routeMinTxt: { color: theme.text, fontSize: 13, fontWeight: "800" },
  // Phase E.5 — "N nouveaux signalements" banner (top). Full-width chip that
  // sits below the top filters row, above the map markers.
  newBanner: {
    marginTop: spacing.sm,
    // 24/07/2026 (bandeau qui chevauchait le bouton zoom au démarrage) —
    // couloir libre à droite : colonne zoom fixe 44 px + marges.
    marginLeft: spacing.md,
    marginRight: 44 + spacing.md + spacing.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: radii.md,
    backgroundColor: theme.primary,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    shadowColor: "#000",
    shadowOpacity: 0.25,
    shadowRadius: 8,
    shadowOffset: { width: 0, height: 3 },
    elevation: 6,
  },
  newBannerDot: {
    width: 8, height: 8, borderRadius: 4,
    backgroundColor: theme.bg,
  },
  newBannerText: {
    flex: 1,
    color: theme.bg,
    fontWeight: "800",
    fontSize: 13,
    letterSpacing: 0.2,
  },
  // Phase I — Toggle nav button. Same circular footprint as locBtn, sits
  // right above it in the FAB stack. Triangle is built with CSS borders
  // so we don't ship another asset.
  // Phase K.13 — Radar toggle button (Vigie mode only). Same 48×48 footprint
  // as navBtn to align vertically. Uses Ionicons "radio" glyph which reads
  // universally as radar/wave emission. Toggled visually via colour + border
  // + a small strike bar overlay when disabled.
  alertCfgBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: theme.bg2,
    borderWidth: 1.5,
    borderColor: "#F4A261",
    shadowColor: "#000",
    shadowOpacity: 0.35,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 3 },
    elevation: 5,
  },
  alertCfgGear: {
    position: "absolute",
    right: 4,
    bottom: 4,
    width: 15,
    height: 15,
    borderRadius: 8,
    backgroundColor: "#F4A261",
    alignItems: "center",
    justifyContent: "center",
  },
  activeAlertCard: {
    position: "absolute",
    left: 12,
    right: 12,
    zIndex: 60,
    backgroundColor: "rgba(11,19,43,0.96)",
    borderWidth: 1.5,
    borderRadius: 16,
    padding: 14,
    gap: 10,
  },
  activeAlertHead: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  activeAlertText: { flex: 1, fontWeight: "800", fontSize: 13, lineHeight: 18 },
  stopAlertBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: "#E63946",
    borderRadius: 12,
    paddingVertical: 13,
    minHeight: 48,
  },
  stopAlertText: { color: "#fff", fontWeight: "900", fontSize: 15 },
  alertGearRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, paddingVertical: 8, minHeight: 36,
  },
  alertGearText: { color: theme.textDim, fontWeight: "800", fontSize: 12 },
  quickSettingsScroll: { maxHeight: 290 },
  stoppedAlertPill: {
    position: "absolute",
    left: 12,
    zIndex: 60,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "rgba(11,19,43,0.94)",
    borderWidth: 1,
    borderRadius: 20,
    paddingLeft: 12,
    paddingRight: 6,
    paddingVertical: 7,
  },
  stoppedAlertText: { color: theme.textMute, fontWeight: "700", fontSize: 12 },
  reactivateBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: 14,
    minHeight: 30,
  },
  reactivateBtnText: { color: theme.bg, fontWeight: "900", fontSize: 12 },
  stoppedAlertClose: { padding: 6 },
  alertSheetBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    justifyContent: "flex-end",
  },
  alertSheet: {
    backgroundColor: theme.bg2,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 18,
    paddingTop: 8,
    maxHeight: "82%",
  },
  alertSheetHandle: {
    alignSelf: "center",
    width: 42,
    height: 4,
    borderRadius: 2,
    backgroundColor: theme.border,
    marginBottom: 8,
  },
  alertSheetHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 10,
  },
  alertSheetTitle: { flex: 1, color: theme.text, fontWeight: "900", fontSize: 16 },
  alertSheetClose: { padding: 6 },
  radarBtn: {
    width: 44, height: 44, borderRadius: 22,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1,
  },
  radarBtnOn: {
    backgroundColor: "rgba(230,57,70,0.15)",
    borderColor: "#E63946",
    shadowColor: "#E63946", shadowOpacity: 0.55, shadowRadius: 10,
    shadowOffset: { width: 0, height: 0 },
    elevation: 8,
  },
  radarBtnOff: {
    backgroundColor: theme.bg2,
    borderColor: theme.border,
  },
  radarBtnStrike: {
    position: "absolute",
    left: 8, right: 8, top: 22,
    height: 2, borderRadius: 1,
    backgroundColor: theme.textMute,
    transform: [{ rotate: "-45deg" }],
  },
  navBtn: {
    width: 44, height: 44, borderRadius: 22, backgroundColor: theme.bg2,
    alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: theme.border,
  },
  navBtnOn: {
    backgroundColor: "rgba(230,57,70,0.15)",
    borderColor: "#E63946",
    shadowColor: "#E63946", shadowOpacity: 0.55, shadowRadius: 10,
    shadowOffset: { width: 0, height: 0 },
    elevation: 8,
  },
  navArrow: {
    width: 0, height: 0,
    borderLeftWidth: 9, borderRightWidth: 9, borderBottomWidth: 18,
    borderLeftColor: "transparent", borderRightColor: "transparent",
  },
  navArrowOff: { borderBottomColor: theme.textMute },
  navArrowOn: { borderBottomColor: "#E63946" },
  // Phase K — Mini-cone config button (visible when navMode is ON).
  coneBtn: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: "rgba(244,162,97,0.18)",
    borderWidth: 1, borderColor: "#F4A261",
    alignItems: "center", justifyContent: "center",
    shadowColor: "#F4A261", shadowOpacity: 0.4, shadowRadius: 8,
    shadowOffset: { width: 0, height: 0 }, elevation: 6,
  },
  coneBtnArc: {
    width: 0, height: 0,
    borderLeftWidth: 8, borderRightWidth: 8, borderBottomWidth: 14,
    borderLeftColor: "transparent", borderRightColor: "transparent",
    borderBottomColor: "#F4A261",
    marginBottom: 1,
  },
  coneBtnLabel: {
    color: "#F4A261", fontWeight: "900", fontSize: 9, letterSpacing: 0,
    marginTop: -1,
  },
  sheetSubtitle: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  // Cone preview: double-cone (flare + corridor) with the boat at the bottom
  // apex. Corridor rectangle sits above the flare triangle (which points
  // DOWN, apex at bottom). Colors + subtle border echo the map cone.
  conePreviewBox: {
    height: 170,
    marginBottom: spacing.md, marginTop: 4,
    backgroundColor: "rgba(11,19,43,0.55)",
    borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    position: "relative",
    overflow: "hidden",
  },
  conePreviewCorridor: {
    backgroundColor: "rgba(244,162,97,0.18)",
    borderTopWidth: 2.2, borderLeftWidth: 2.2, borderRightWidth: 2.2,
    borderColor: "#F4A261",
    borderTopLeftRadius: 3, borderTopRightRadius: 3,
  },
  conePreviewFlare: {
    // Triangle pointing DOWN (apex at bottom): borderTop is filled, others
    // are transparent. Sizes are set inline based on the angle so the flare
    // aligns pixel-perfect with the corridor width.
    width: 0, height: 0,
    borderStyle: "solid",
    borderLeftColor: "transparent",
    borderRightColor: "transparent",
    borderTopColor: "rgba(244,162,97,0.28)",
    marginTop: -1,
  },
  conePreviewBoatDot: {
    width: 14, height: 14, borderRadius: 7,
    backgroundColor: "#E63946",
    borderWidth: 2, borderColor: "#0B132B",
    marginTop: -6,
    shadowColor: "#E63946", shadowOpacity: 0.5,
    shadowRadius: 6, shadowOffset: { width: 0, height: 0 },
  },
  conePreviewLabel: {
    position: "absolute", top: 10, right: 14,
    color: "#F4A261", fontWeight: "900", fontSize: 20,
    letterSpacing: 0.5,
  },
  conePreviewDim: {
    position: "absolute", left: 12, bottom: 8, right: 60,
    color: "rgba(232,236,251,0.55)", fontSize: 10,
    fontWeight: "500", letterSpacing: 0.2,
  },
  conePresetRow: {
    flexDirection: "row", flexWrap: "wrap", gap: 8,
    marginTop: spacing.xs, marginBottom: spacing.md,
  },
  // Phase K — Slider row: label ⟷ current value in bold amber.
  coneSliderRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginTop: spacing.xs,
  },
  coneSliderValue: {
    color: "#F4A261", fontWeight: "900", fontSize: 20,
    letterSpacing: 0.5,
  },
  coneSlider: {
    width: "100%",
    // 16/07/2026 (retour terrain) — hauteur portée à 56 px pour élargir la
    // zone tactile sur la popup de réglage rapide du cône.
    height: 56,
    marginTop: 2,
  },
  // ── Popup unité d'échelle (16/07/2026) ────────────────────────────────
  unitPickerBackdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "center", alignItems: "center", padding: spacing.lg,
  },
  unitPickerSheet: {
    width: "100%", maxWidth: 380,
    backgroundColor: theme.bg2, borderRadius: 14,
    borderWidth: 1, borderColor: theme.border,
    padding: spacing.md, gap: 10,
  },
  unitPickerHeader: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 },
  // 26/08/2026 — bandeau « faible hauteur d'eau » du menu de la route
  // (tap sur une zone rouge du tracé).
  routeDangerBanner: {
    flexDirection: "row", alignItems: "flex-start", gap: 10,
    backgroundColor: "rgba(255,23,68,0.12)", borderRadius: 10,
    borderWidth: 1, borderColor: "rgba(255,23,68,0.45)",
    padding: 10, marginBottom: 4,
  },
  routeDangerTitle: { color: "#FF5252", fontSize: 14, fontWeight: "800" },
  routeDangerText: { color: theme.text, fontSize: 12.5, lineHeight: 17, marginTop: 2 },
  unitPickerTitle: { color: theme.text, fontSize: 15, fontWeight: "800" },
  unitPickerRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    minHeight: 56,
    borderRadius: 10, backgroundColor: theme.bg3,
    borderWidth: 1, borderColor: theme.border,
    paddingHorizontal: 12, paddingVertical: 10,
  },
  unitPickerRowActive: { borderColor: theme.primary },
  unitPickerLabel: { color: theme.text, fontSize: 14, fontWeight: "800" },
  unitPickerHint: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  // ── Bandeau intro one-shot v2 cône coloré (17/07/2026) ────────────────
  introBannerWrap: {
    // 24/07/2026 — couloir libre à droite (colonne zoom fixe 44 px + marges)
    // pour ne plus chevaucher les boutons zoom au démarrage.
    position: "absolute", left: spacing.md, right: 44 + spacing.md + spacing.sm, zIndex: 25,
  },
  introBanner: {
    flexDirection: "row", gap: 10, alignItems: "flex-start",
    backgroundColor: "rgba(11,19,43,0.95)",
    borderRadius: 12,
    borderWidth: 1, borderColor: theme.primary,
    padding: 12,
    shadowColor: "#000", shadowOpacity: 0.35, shadowRadius: 8, shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
  introBannerTitle: { color: theme.text, fontSize: 13, fontWeight: "800", marginBottom: 4 },
  introBannerBody: { color: theme.textDim, fontSize: 12, lineHeight: 17 },
  introBannerBtn: {
    marginTop: 10, alignSelf: "flex-start",
    backgroundColor: theme.primary, paddingVertical: 8, paddingHorizontal: 14,
    borderRadius: 8,
  },
  introBannerBtnText: { color: "#06222E", fontSize: 12, fontWeight: "800" },
  coneSliderScale: {
    flexDirection: "row", justifyContent: "space-between",
    paddingHorizontal: 6, marginTop: -6, marginBottom: spacing.md,
  },
  coneSliderScaleText: {
    color: theme.textDim, fontSize: 11, fontWeight: "600",
  },
  coneInfoRow: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    paddingHorizontal: 4, paddingVertical: 8,
    marginBottom: spacing.sm,
  },
  coneDistanceBlock: {
    borderTopWidth: 1, borderTopColor: theme.border,
    paddingTop: spacing.md, marginBottom: spacing.sm,
  },
  proximityWrap: { position: "absolute", left: 12, right: 12, zIndex: 40 },
  coneInfoText: { color: theme.textDim, fontSize: 11, lineHeight: 15, flex: 1 },
  fab: {
    backgroundColor: theme.primary, paddingHorizontal: 18, paddingVertical: 14,
    borderRadius: radii.pill, flexDirection: "row", alignItems: "center", gap: 6,
    minHeight: 56, elevation: 8,
  },
  fabLabel: { color: theme.bg, fontWeight: "900", fontSize: 16, marginLeft: 2 },
  pickBar: {
    position: "absolute", left: 0, right: 0, bottom: 0,
    backgroundColor: theme.bg2, borderTopWidth: 2, borderTopColor: theme.primary,
    padding: spacing.md, gap: spacing.sm,
  },
  pickTitleRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  pickTitle: { color: theme.text, fontWeight: "800", fontSize: 14, flex: 1 },
  pickCoords: { color: theme.primary, fontWeight: "900", fontSize: 16 },
  pickActions: { flexDirection: "row", gap: spacing.sm },
  pickCancel: {
    flex: 1, backgroundColor: theme.bg3, padding: 14, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    borderWidth: 1, borderColor: theme.border, minHeight: 52,
  },
  pickCancelText: { color: theme.text, fontWeight: "800" },
  pickContinue: {
    flex: 2, backgroundColor: theme.primary, padding: 14, borderRadius: radii.md,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    minHeight: 52,
  },
  pickContinueText: { color: theme.bg, fontWeight: "900", fontSize: 15 },
  loading: { ...StyleSheet.absoluteFillObject, alignItems: "center", justifyContent: "center" },
  // PHASE 4 — Bottom-sheet filter.
  sheetBackdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.55)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.bg2, borderTopLeftRadius: 22, borderTopRightRadius: 22,
    paddingHorizontal: spacing.md, paddingTop: spacing.sm, paddingBottom: spacing.lg,
    borderTopWidth: 1, borderColor: theme.border,
  },
  sheetHandle: {
    width: 44, height: 4, borderRadius: 2, backgroundColor: theme.border,
    alignSelf: "center", marginBottom: spacing.sm,
  },
  sheetHeader: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  sheetTitle: { color: theme.text, fontWeight: "900", fontSize: 18 },
  sheetSectionRow: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    marginTop: spacing.xs, marginBottom: spacing.xs,
  },
  sheetSection: { color: theme.textDim, fontWeight: "800", fontSize: 12, textTransform: "uppercase", letterSpacing: 0.6 },
  sheetLink: { color: theme.primary, fontWeight: "800", fontSize: 12 },
  sheetLinkSep: { color: theme.textMute, fontWeight: "800", fontSize: 12 },
  sheetRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: 12, paddingHorizontal: 10, borderRadius: radii.md,
    backgroundColor: theme.bg3, marginVertical: 4, borderWidth: 1, borderColor: "transparent",
  },
  sheetRowOn: { borderColor: theme.primary },
  sheetDot: { width: 30, height: 30, borderRadius: 15, alignItems: "center", justifyContent: "center" },
  sheetRowLabel: { color: theme.text, fontWeight: "800", fontSize: 14 },
  sheetRowDesc: { color: theme.textDim, fontSize: 12, marginTop: 1 },
  sheetDivider: { height: 1, backgroundColor: theme.border, marginVertical: spacing.sm },
  sheetTogglesRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingVertical: 10, marginBottom: spacing.sm,
  },
  sheetApply: {
    backgroundColor: theme.primary, paddingVertical: 14, borderRadius: radii.md,
    alignItems: "center", justifyContent: "center", marginTop: spacing.sm,
  },
  sheetApplyText: { color: theme.bg, fontWeight: "900", fontSize: 15 },
});
