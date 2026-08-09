// SignalMar — Marine ranks ladder modal.
// Tapping the user's title/rank badge in the Profile screen pops up this
// inspirational ladder. It lists every rank in order, with the current one
// highlighted (glowing ring + "VOUS ÊTES ICI" tag) and the next one tagged
// "PROCHAIN GRADE — X pts restants". The maintainer's custom title
// ("Amiral Modérateur") is displayed as a separate honorary badge at the
// top, distinct from the regular ladder.

import { Ionicons } from "@expo/vector-icons";
import {
  Dimensions,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { MARINE_RANKS, type MarineRank, rankForPoints, nextRank } from "@/src/lib/marine-ranks";
import { radii, spacing, theme } from "@/src/lib/theme";

const SHEET_HEIGHT = Math.round(Dimensions.get("window").height * 0.92);

type Props = {
  visible: boolean;
  onClose: () => void;
  points: number;
  /** Optional honorary custom title (e.g. "Amiral Modérateur"). */
  customTitle?: string | null;
};

export function RanksModal({ visible, onClose, points, customTitle }: Props) {
  const current = rankForPoints(points);
  const upcoming = nextRank(points);
  const ptsToNext = upcoming ? Math.max(0, upcoming.min_points - points) : 0;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      {/* Backdrop sits BEHIND the sheet (absoluteFill) so taps on the sheet
          don't bubble up to it on Android. This is the pattern that finally
          lets the rank-ladder ScrollView capture vertical pan gestures in
          Expo Go — the previous attempts wrapped the sheet in a Pressable /
          a View with onStartShouldSetResponder which both swallowed touches
          before they reached the ScrollView. */}
      <View style={styles.modalRoot}>
        <Pressable
          style={StyleSheet.absoluteFillObject}
          onPress={onClose}
          testID="ranks-modal-backdrop"
        />
        <View style={styles.sheet}>
          {/* Bouton close en absolute pour ne pas bouger en scroll. */}
          <TouchableOpacity
            style={styles.closeAbs}
            onPress={onClose}
            hitSlop={{ top: 12, right: 12, bottom: 12, left: 12 }}
            testID="ranks-modal-close"
          >
            <Ionicons name="close" size={22} color={theme.text} />
          </TouchableOpacity>

          {/* ScrollView UNIQUE qui contient TOUT le contenu — garantit
              que rien n'est tronqué quelle que soit la hauteur du modal,
              et évite les problèmes de scroll imbriqué sur Android. */}
          <ScrollView
            style={styles.scrollFlex}
            contentContainerStyle={styles.scrollContent}
            showsVerticalScrollIndicator
            bounces
            overScrollMode="always"
          >
            <View style={styles.handle} />
            <View style={styles.header}>
              <View style={{ flex: 1, paddingRight: 32 }}>
                <Text style={styles.title}>Grades — Marine Nationale</Text>
                <Text style={styles.sub}>
                  Cumulez des points en temps passé en mer (1 pt/h, 12 pts max/jour).
                </Text>
              </View>
            </View>

            {customTitle ? (
              <View style={styles.customTitleCard}>
                <View style={styles.customTitleBadge}>
                  <Ionicons name="ribbon" size={20} color="#FFD166" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.customTitleLabel}>{customTitle}</Text>
                  <Text style={styles.customTitleHint}>Titre honorifique — hors-grille.</Text>
                </View>
              </View>
            ) : null}

            <View style={styles.youCard}>
              <Text style={styles.youLabel}>Vous êtes</Text>
              <Text style={[styles.youRank, { color: current.color }]}>{current.label}</Text>
              <View style={styles.youProgressRow}>
                <View style={[styles.youDot, { backgroundColor: current.color }]} />
                <Text style={styles.youPoints}>{points} pts</Text>
                {upcoming ? (
                  <>
                    <Text style={styles.youSep}>→</Text>
                    <Text style={styles.youNext}>
                      {ptsToNext} pts pour <Text style={{ fontWeight: "900" }}>{upcoming.label}</Text>
                    </Text>
                  </>
                ) : (
                  <Text style={styles.youNext}>Sommet atteint ⚓</Text>
                )}
              </View>
            </View>

            <Text style={styles.ladderHeader}>Tous les grades</Text>
            {MARINE_RANKS.map((r) => (
              <RankRow
                key={r.id}
                rank={r}
                isCurrent={r.id === current.id}
                isNext={!!upcoming && r.id === upcoming.id}
                unlocked={points >= r.min_points}
              />
            ))}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

function RankRow({
  rank,
  isCurrent,
  isNext,
  unlocked,
}: {
  rank: MarineRank;
  isCurrent: boolean;
  isNext: boolean;
  unlocked: boolean;
}) {
  return (
    <View
      style={[
        styles.row,
        isCurrent && { borderColor: rank.color, backgroundColor: "rgba(72,202,228,0.08)" },
      ]}
      testID={`rank-row-${rank.id}`}
    >
      <View
        style={[
          styles.iconBubble,
          { backgroundColor: unlocked ? rank.color : "rgba(255,255,255,0.08)" },
          isCurrent && styles.iconBubbleGlow,
        ]}
      >
        <Ionicons
          name={rank.icon as never}
          size={18}
          color={unlocked ? theme.bg : theme.textMute}
        />
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6 }}>
          <Text
            style={[styles.rowLabel, !unlocked && { color: theme.textDim }]}
            numberOfLines={2}
          >{rank.label}</Text>
          {isCurrent && (
            <View style={[styles.tag, { backgroundColor: rank.color }]}>
              <Text style={styles.tagText}>VOUS ÊTES ICI</Text>
            </View>
          )}
          {isNext && (
            <View style={[styles.tag, { backgroundColor: "rgba(255,209,102,0.18)", borderColor: "#FFD166", borderWidth: 1 }]}>
              <Text style={[styles.tagText, { color: "#FFD166" }]}>PROCHAIN</Text>
            </View>
          )}
        </View>
        <Text style={styles.rowTag}>{rank.tagline}</Text>
      </View>
      <Text
        style={[styles.rowPts, { color: unlocked ? rank.color : theme.textMute, marginLeft: 8 }]}
        numberOfLines={1}
      >
        {rank.min_points}
        <Text style={{ fontSize: 10, color: theme.textDim }}> pts</Text>
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  modalRoot: { flex: 1, backgroundColor: "rgba(0,0,0,0.6)", justifyContent: "flex-end" },
  sheet: {
    backgroundColor: theme.bg2, borderTopLeftRadius: 24, borderTopRightRadius: 24,
    // Hauteur explicite en pixels (calculée depuis Dimensions) — fiable
    // sur Android où "92%" peut résoudre à 0 si le parent n'a pas de
    // hauteur déterminée. Le ScrollView interne hérite ainsi d'un
    // conteneur borné et défile correctement.
    height: SHEET_HEIGHT,
    overflow: "hidden",
  },
  closeAbs: {
    position: "absolute", top: 12, right: 12, zIndex: 5,
    width: 32, height: 32, borderRadius: 16,
    backgroundColor: theme.bg3,
    alignItems: "center", justifyContent: "center",
  },
  scrollFlex: { flex: 1 },
  scrollContent: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.sm,
    paddingBottom: spacing.xxl,
  },
  handle: {
    width: 48, height: 4, borderRadius: 2, backgroundColor: theme.border,
    alignSelf: "center", marginBottom: spacing.sm,
  },
  header: {
    flexDirection: "row", alignItems: "flex-start", gap: spacing.sm, marginBottom: spacing.sm,
  },
  title: { color: theme.text, fontWeight: "900", fontSize: 19 },
  sub: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  customTitleCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    backgroundColor: "rgba(255,209,102,0.10)",
    borderColor: "#FFD166", borderWidth: 1,
    borderRadius: radii.md, padding: spacing.sm, marginBottom: spacing.sm,
  },
  customTitleBadge: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: "rgba(255,209,102,0.18)",
    alignItems: "center", justifyContent: "center",
  },
  customTitleLabel: { color: "#FFD166", fontWeight: "900", fontSize: 15 },
  customTitleHint: { color: theme.textDim, fontSize: 11, marginTop: 1 },
  youCard: {
    backgroundColor: theme.bg3, borderRadius: radii.md, padding: spacing.md,
    marginBottom: spacing.sm,
  },
  youLabel: { color: theme.textDim, fontSize: 11, textTransform: "uppercase", letterSpacing: 0.6, fontWeight: "800" },
  youRank: { fontSize: 22, fontWeight: "900", marginTop: 2 },
  youProgressRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6, flexWrap: "wrap" },
  youDot: { width: 8, height: 8, borderRadius: 4 },
  youPoints: { color: theme.text, fontWeight: "800", fontSize: 13 },
  youSep: { color: theme.textMute, fontWeight: "800" },
  youNext: { color: theme.textDim, fontSize: 12, flexShrink: 1 },
  ladderHeader: {
    color: theme.textDim, fontSize: 11, fontWeight: "900",
    textTransform: "uppercase", letterSpacing: 0.6,
    marginTop: spacing.xs, marginBottom: 6, paddingHorizontal: 2,
  },
  row: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    padding: 12, borderRadius: radii.md, marginVertical: 4,
    borderWidth: 1, borderColor: "transparent",
    backgroundColor: theme.bg3,
  },
  iconBubble: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
  },
  iconBubbleGlow: {
    shadowColor: "#48CAE4", shadowOpacity: 0.6, shadowRadius: 10, shadowOffset: { width: 0, height: 0 },
    elevation: 6,
  },
  rowLabel: { color: theme.text, fontWeight: "800", fontSize: 14 },
  rowTag: { color: theme.textDim, fontSize: 11, marginTop: 1 },
  rowPts: { fontWeight: "900", fontSize: 15 },
  tag: {
    paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6,
  },
  tagText: { color: theme.bg, fontSize: 9, fontWeight: "900", letterSpacing: 0.4 },
});
