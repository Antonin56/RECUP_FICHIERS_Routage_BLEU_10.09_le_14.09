import { useMemo, useState } from "react";
import {
  FlatList,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { theme, spacing, radii } from "@/src/lib/theme";
import { BuoyVisual } from "@/src/components/BuoyVisual";
import {
  BUOYS,
  SAFETY_CATEGORIES,
  SAFETY_FOOTNOTES,
  SAFETY_RULES,
  materialsFor,
  type CategoryId,
  type FootnoteId,
} from "@/src/lib/safety-data";

type TabId = "checklist" | "buoys" | "rules";

export default function SafetyScreen() {
  const [tab, setTab] = useState<TabId>("checklist");
  const [category, setCategory] = useState<CategoryId>("cotier");
  const [checked, setChecked] = useState<Record<string, boolean>>({});
  const [activeFootnote, setActiveFootnote] = useState<FootnoteId | null>(null);
  // Visualiseur de bouées plein écran (11/07/2026) : tap sur une carte →
  // bouée agrandie, balayage vertical = bouée suivante (pas de boucle),
  // tap sur l'image ou la croix = fermeture.
  const [buoyViewer, setBuoyViewer] = useState<number | null>(null);
  const [buoyPage, setBuoyPage] = useState(0);
  const { height: winH } = useWindowDimensions();
  const insets = useSafeAreaInsets();

  const materials = useMemo(() => materialsFor(category), [category]);
  const progress = useMemo(() => {
    const n = materials.length;
    if (!n) return 0;
    const done = materials.filter((m) => checked[m.id]).length;
    return Math.round((done / n) * 100);
  }, [materials, checked]);

  const openNote = (fn: FootnoteId) => setActiveFootnote(fn);
  const closeNote = () => setActiveFootnote(null);
  const noteContent = activeFootnote ? SAFETY_FOOTNOTES[activeFootnote] : null;

  return (
    <SafeAreaView style={styles.root} edges={["top", "bottom"]}>
      <View style={styles.header}>
        <Text style={styles.title}>Sécurité en mer</Text>
        <Text style={styles.sub}>Division 240 — vérifiez avant de partir.</Text>
      </View>

      <View style={styles.tabsRow}>
        {([
          { id: "checklist", label: "Checklist", icon: "checkbox-outline" },
          { id: "buoys",     label: "Bouées IALA", icon: "compass-outline" },
          { id: "rules",     label: "Règles",    icon: "book-outline" },
        ] as const).map((t) => (
          <TouchableOpacity
            key={t.id}
            style={[styles.tabBtn, tab === t.id && styles.tabBtnOn]}
            onPress={() => setTab(t.id)}
            testID={`safety-tab-${t.id}`}
          >
            <Ionicons name={t.icon as never} size={16} color={tab === t.id ? theme.bg : theme.text} />
            <Text style={[styles.tabLabel, tab === t.id && { color: theme.bg }]}>{t.label}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <ScrollView contentContainerStyle={styles.scroll} showsVerticalScrollIndicator>
        {tab === "checklist" && (
          <>
            <Text style={styles.section}>Catégorie de navigation</Text>
            <View style={styles.catGrid}>
              {SAFETY_CATEGORIES.map((c) => {
                const on = c.id === category;
                return (
                  <TouchableOpacity
                    key={c.id}
                    style={[styles.catCard, on && { borderColor: c.color, backgroundColor: c.color + "22" }]}
                    onPress={() => setCategory(c.id)}
                    testID={`safety-cat-${c.id}`}
                    activeOpacity={0.85}
                  >
                    <Ionicons name={c.icon as never} size={20} color={on ? c.color : theme.textDim} />
                    <Text style={[styles.catLabel, on && { color: c.color }]} numberOfLines={1}>{c.label}</Text>
                    <Text style={styles.catRange} numberOfLines={2}>{c.range}</Text>
                  </TouchableOpacity>
                );
              })}
            </View>

            {/* Astérisque "Abri" — tap pour voir la définition officielle */}
            <TouchableOpacity
              style={styles.abriBtn}
              onPress={() => openNote("abri")}
              testID="safety-footnote-abri"
              activeOpacity={0.7}
            >
              <Ionicons name="information-circle-outline" size={14} color={theme.primary} />
              <Text style={styles.abriText}>
                <Text style={{ color: theme.primary, fontWeight: "900" }}>*</Text> Tap pour la définition officielle d{"’"}un « abri »
              </Text>
            </TouchableOpacity>

            <View style={styles.progressBar}>
              <View style={[styles.progressFill, { width: `${progress}%` }]} />
              <Text style={styles.progressText}>
                {progress}% — {materials.filter((m) => checked[m.id]).length}/{materials.length}
              </Text>
            </View>

            <Text style={styles.section}>
              Matériel obligatoire — Catégorie {SAFETY_CATEGORIES.find((c) => c.id === category)?.label}
            </Text>
            {materials.map((m) => {
              const on = !!checked[m.id];
              const hasNote = (m.footnotes?.length ?? 0) > 0;
              return (
                <View
                  key={m.id}
                  style={[styles.row, on && styles.rowOn]}
                  testID={`safety-mat-${m.id}`}
                >
                  <TouchableOpacity
                    style={styles.rowCheck}
                    onPress={() => setChecked((p) => ({ ...p, [m.id]: !p[m.id] }))}
                    activeOpacity={0.7}
                    testID={`safety-mat-toggle-${m.id}`}
                  >
                    <Ionicons
                      name={on ? "checkmark-circle" : "ellipse-outline"}
                      size={24}
                      color={on ? theme.success : theme.textDim}
                    />
                  </TouchableOpacity>

                  <TouchableOpacity
                    style={{ flex: 1 }}
                    onPress={() => setChecked((p) => ({ ...p, [m.id]: !p[m.id] }))}
                    activeOpacity={0.7}
                  >
                    <Text
                      style={[
                        styles.itemLabel,
                        on && { textDecorationLine: "line-through", color: theme.textDim },
                      ]}
                    >
                      {m.label}
                    </Text>
                  </TouchableOpacity>

                  {hasNote && (
                    <TouchableOpacity
                      style={styles.noteBadge}
                      onPress={() => openNote(m.footnotes![0])}
                      hitSlop={{ top: 10, right: 10, bottom: 10, left: 10 }}
                      testID={`safety-mat-note-${m.id}`}
                      activeOpacity={0.7}
                    >
                      <Text style={styles.noteBadgeText}>?</Text>
                    </TouchableOpacity>
                  )}
                </View>
              );
            })}

            <Text style={styles.disclaimer}>
              Source : Arrêté du 11 mars 2008 modifié — Division 240 (version 02/2024).
              Vérifiez la conformité auprès des Affaires Maritimes.
            </Text>
          </>
        )}

        {tab === "buoys" && (
          <>
            <Text style={styles.section}>Bouées IALA — Région A</Text>
            <Text style={styles.intro}>
              Système de balisage maritime utilisé en Europe, Afrique, Asie et Océanie.
              Touchez une bouée pour l{"\u2019"}agrandir.
            </Text>
            {BUOYS.map((b, i) => (
              <TouchableOpacity
                key={b.id}
                style={styles.buoyCard}
                onPress={() => { setBuoyPage(i); setBuoyViewer(i); }}
                activeOpacity={0.8}
                testID={`buoy-card-${b.id}`}
              >
                <View style={styles.buoyChart}>
                  <BuoyVisual buoy={b} size={56} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.buoyName}>{b.name}</Text>
                  <Text style={styles.buoyDesc}>{b.description}</Text>
                  <View style={styles.buoyLightRow}>
                    <Ionicons name="bulb-outline" size={12} color="#FFD22E" />
                    <Text style={styles.buoyLight}>{b.light}</Text>
                  </View>
                </View>
                <Ionicons name="expand-outline" size={16} color={theme.textMute} />
              </TouchableOpacity>
            ))}
          </>
        )}

        {tab === "rules" && (
          <>
            <Text style={styles.section}>Règles essentielles</Text>
            {SAFETY_RULES.map((r) => (
              <View key={r.id} style={styles.ruleCard}>
                <View style={styles.ruleIconWrap}>
                  <Ionicons name={r.icon as never} size={22} color={theme.primary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.ruleTitle}>{r.title}</Text>
                  <Text style={styles.ruleBody}>{r.body}</Text>
                </View>
              </View>
            ))}
          </>
        )}
      </ScrollView>

      {/* Petite popup pour les notes de bas de page */}
      <Modal
        visible={!!noteContent}
        transparent
        animationType="fade"
        onRequestClose={closeNote}
      >
        <Pressable style={styles.popupBackdrop} onPress={closeNote}>
          <Pressable style={styles.popupCard} onPress={() => { /* swallow */ }}>
            {noteContent && (
              <>
                <View style={styles.popupHeader}>
                  <Ionicons name="information-circle" size={18} color={theme.primary} />
                  <Text style={styles.popupTitle} numberOfLines={2}>
                    {noteContent.title}
                  </Text>
                  <TouchableOpacity
                    onPress={closeNote}
                    hitSlop={{ top: 12, right: 12, bottom: 12, left: 12 }}
                    testID="safety-note-close"
                  >
                    <Ionicons name="close" size={20} color={theme.textDim} />
                  </TouchableOpacity>
                </View>
                <ScrollView
                  style={{ maxHeight: 380 }}
                  contentContainerStyle={{ paddingBottom: spacing.sm }}
                  showsVerticalScrollIndicator
                >
                  <Text style={styles.popupBody}>{noteContent.body}</Text>
                </ScrollView>
                <Text style={styles.popupSource}>Division 240 — texte officiel</Text>
              </>
            )}
          </Pressable>
        </Pressable>
      </Modal>

      {/* Visualiseur de bouées plein écran (11/07/2026).
          Balayage vertical = bouée suivante/précédente (paging, PAS de
          boucle : le scroll s'arrête naturellement au dernier élément).
          Tap sur la page ou sur la croix = fermeture. */}
      <Modal
        visible={buoyViewer != null}
        animationType="fade"
        onRequestClose={() => setBuoyViewer(null)}
      >
        <View style={styles.viewerRoot}>
          <FlatList
            data={BUOYS}
            keyExtractor={(b) => b.id}
            pagingEnabled
            showsVerticalScrollIndicator={false}
            initialScrollIndex={buoyViewer ?? 0}
            getItemLayout={(_, i) => ({ length: winH, offset: winH * i, index: i })}
            onMomentumScrollEnd={(e) => {
              setBuoyPage(Math.min(BUOYS.length - 1,
                Math.max(0, Math.round(e.nativeEvent.contentOffset.y / winH))));
            }}
            // RN-Web n'émet pas les événements momentum → fallback onScroll
            // pour tenir le compteur « x / N » à jour sur le web aussi.
            onScroll={(e) => {
              setBuoyPage(Math.min(BUOYS.length - 1,
                Math.max(0, Math.round(e.nativeEvent.contentOffset.y / winH))));
            }}
            scrollEventThrottle={64}
            renderItem={({ item }) => (
              <Pressable
                style={[styles.viewerPage, { height: winH }]}
                onPress={() => setBuoyViewer(null)}
                testID={`buoy-viewer-page-${item.id}`}
              >
                {/* Fond BLANC derrière la bouée agrandie (retour user 11/07) :
                    fait ressortir les bandes noires/rouges comme sur la
                    planche officielle. */}
                <View style={styles.viewerImgCard}>
                  <BuoyVisual buoy={item} size={165} />
                </View>
                <Text style={styles.viewerName}>{item.name}</Text>
                <Text style={styles.viewerDesc}>{item.description}</Text>
                <View style={styles.viewerLightRow}>
                  <Ionicons name="bulb" size={15} color="#FFD22E" />
                  <Text style={styles.viewerLight}>{item.light}</Text>
                </View>
              </Pressable>
            )}
          />
          <TouchableOpacity
            style={[styles.viewerClose, { top: insets.top + 10 }]}
            onPress={() => setBuoyViewer(null)}
            hitSlop={12}
            testID="buoy-viewer-close"
          >
            <Ionicons name="close" size={26} color={theme.text} />
          </TouchableOpacity>
          <View style={[styles.viewerFooter, { bottom: insets.bottom + 14 }]} pointerEvents="none">
            <View style={styles.viewerCounter}>
              <Text style={styles.viewerCounterTxt}>{buoyPage + 1} / {BUOYS.length}</Text>
            </View>
            {buoyPage < BUOYS.length - 1 && (
              <Text style={styles.viewerHint}>Balayez vers le haut — bouée suivante</Text>
            )}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: theme.bg },
  header: { paddingHorizontal: spacing.md, paddingTop: spacing.md, paddingBottom: spacing.sm },
  title: { color: theme.text, fontSize: 22, fontWeight: "900" },
  sub: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  tabsRow: {
    flexDirection: "row", gap: 6, paddingHorizontal: spacing.md, marginBottom: spacing.sm,
  },
  tabBtn: {
    flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: theme.bg2, borderColor: theme.border, borderWidth: 1,
    paddingHorizontal: spacing.sm, paddingVertical: 10, borderRadius: radii.pill,
  },
  tabBtnOn: { backgroundColor: theme.primary, borderColor: theme.primary },
  tabLabel: { color: theme.text, fontWeight: "800", fontSize: 12 },
  scroll: { paddingHorizontal: spacing.md, paddingBottom: spacing.xl, gap: spacing.sm },
  section: { color: theme.text, fontWeight: "900", fontSize: 13, marginTop: spacing.sm, letterSpacing: 0.4 },
  intro: { color: theme.textDim, fontSize: 13, lineHeight: 19 },

  catGrid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  catCard: {
    flexBasis: "48%",
    flexGrow: 1,
    minHeight: 78,
    padding: spacing.sm, gap: 4,
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border,
  },
  catLabel: { color: theme.text, fontWeight: "800", fontSize: 13 },
  catRange: { color: theme.textDim, fontSize: 11, lineHeight: 14 },

  abriBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.sm, paddingVertical: 6,
    alignSelf: "flex-start",
  },
  abriText: { color: theme.textDim, fontSize: 11 },

  progressBar: {
    marginTop: spacing.sm,
    height: 26, borderRadius: 13, backgroundColor: theme.bg2,
    borderWidth: 1, borderColor: theme.border,
    overflow: "hidden", justifyContent: "center",
  },
  progressFill: {
    position: "absolute", left: 0, top: 0, bottom: 0,
    backgroundColor: theme.success + "55",
  },
  progressText: { textAlign: "center", color: theme.text, fontWeight: "800", fontSize: 12 },

  row: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: theme.bg2, borderRadius: radii.md, padding: spacing.sm,
    borderWidth: 1, borderColor: theme.border,
  },
  rowOn: { borderColor: theme.success + "66", backgroundColor: theme.success + "10" },
  rowCheck: { paddingRight: 6 },
  itemLabel: { color: theme.text, fontSize: 14, fontWeight: "600", lineHeight: 19 },

  noteBadge: {
    width: 26, height: 26, borderRadius: 13,
    backgroundColor: theme.primary + "22",
    borderWidth: 1, borderColor: theme.primary + "55",
    alignItems: "center", justifyContent: "center",
    marginLeft: 4,
  },
  noteBadgeText: { color: theme.primary, fontWeight: "900", fontSize: 14, marginTop: -1 },

  disclaimer: { color: theme.textMute, fontSize: 11, fontStyle: "italic", marginTop: spacing.sm },

  buoyCard: {
    flexDirection: "row", gap: spacing.sm,
    backgroundColor: theme.bg2, borderRadius: radii.md, padding: spacing.sm,
    borderWidth: 1, borderColor: theme.border, alignItems: "center",
  },
  buoyChart: {
    width: 64, height: 110,
    // Fond "carte marine" : un blanc cassé légèrement bleuté pour faire
    // ressortir les noirs et les rouges des bouées (sans le contraste
    // criard du blanc pur).
    backgroundColor: "#E8EEF2",
    borderRadius: 8,
    borderWidth: 1, borderColor: "#B7C5D1",
    alignItems: "center", justifyContent: "center",
    overflow: "hidden",
  },
  buoyVisual: {
    width: 28, height: 70, borderRadius: 4, overflow: "hidden",
    backgroundColor: theme.bg, position: "relative",
    justifyContent: "flex-start",
  },
  buoyBand: { flex: 1, width: "100%" },
  buoyTop: {
    position: "absolute", top: -16, left: 0, right: 0,
    color: theme.text, fontSize: 12, textAlign: "center", fontWeight: "900",
  },
  buoyName: { color: theme.text, fontWeight: "900", fontSize: 14 },
  buoyDesc: { color: theme.textDim, fontSize: 12, marginTop: 2, lineHeight: 16 },
  buoyLightRow: { flexDirection: "row", alignItems: "center", gap: 5, marginTop: 4 },
  buoyLight: { color: "#FFD22E", fontSize: 11, fontWeight: "700" },
  // ── Visualiseur de bouées plein écran ──
  viewerRoot: { flex: 1, backgroundColor: "#06101F" },
  viewerImgCard: {
    backgroundColor: "#FFFFFF",
    borderRadius: 20,
    paddingVertical: 22,
    paddingHorizontal: 46,
    shadowColor: "#000", shadowOpacity: 0.35, shadowRadius: 14,
    shadowOffset: { width: 0, height: 6 }, elevation: 8,
  },
  viewerPage: {
    alignItems: "center", justifyContent: "center",
    paddingHorizontal: spacing.xl, gap: 10,
  },
  viewerName: { color: theme.text, fontSize: 22, fontWeight: "900", textAlign: "center", marginTop: 14 },
  viewerDesc: { color: theme.textDim, fontSize: 15, lineHeight: 22, textAlign: "center" },
  viewerLightRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 },
  viewerLight: { color: "#FFD22E", fontSize: 13, fontWeight: "800" },
  viewerClose: {
    position: "absolute", right: 16,
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: "rgba(255,255,255,0.10)",
    borderWidth: 1, borderColor: "rgba(255,255,255,0.18)",
    alignItems: "center", justifyContent: "center",
  },
  viewerFooter: { position: "absolute", left: 0, right: 0, alignItems: "center", gap: 6 },
  viewerCounter: {
    backgroundColor: "rgba(255,255,255,0.10)", borderRadius: radii.pill,
    paddingHorizontal: 12, paddingVertical: 4,
  },
  viewerCounterTxt: { color: theme.text, fontSize: 12, fontWeight: "800" },
  viewerHint: { color: theme.textMute, fontSize: 11 },

  ruleCard: {
    flexDirection: "row", gap: spacing.sm,
    backgroundColor: theme.bg2, borderRadius: radii.md, padding: spacing.sm,
    borderWidth: 1, borderColor: theme.border,
  },
  ruleIconWrap: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: theme.primary + "22",
    alignItems: "center", justifyContent: "center",
  },
  ruleTitle: { color: theme.text, fontWeight: "800", fontSize: 14 },
  ruleBody: { color: theme.textDim, fontSize: 12, marginTop: 2, lineHeight: 17 },

  // ── Popup footnote
  popupBackdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.65)",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.md,
  },
  popupCard: {
    width: "100%",
    maxWidth: 420,
    backgroundColor: theme.bg2,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: theme.border,
    padding: spacing.md,
    gap: spacing.xs,
  },
  popupHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 4,
  },
  popupTitle: {
    flex: 1,
    color: theme.text,
    fontWeight: "900",
    fontSize: 15,
  },
  popupBody: {
    color: theme.text,
    fontSize: 13,
    lineHeight: 19,
  },
  popupSource: {
    color: theme.textMute,
    fontSize: 10,
    fontStyle: "italic",
    marginTop: spacing.xs,
    textAlign: "right",
  },
});
