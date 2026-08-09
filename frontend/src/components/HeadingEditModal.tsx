/**
 * HeadingEditModal — Phase E.3
 *
 * Tactile compass widget: the user drags a projection arrow around a fixed
 * center point representing the report position. Live bearing display in
 * the middle, validate / cancel buttons below.
 *
 * Authorisation is enforced by the backend (author OR reliability ≥ 60%);
 * the caller is responsible for only mounting this modal when the current
 * user satisfies that rule.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Animated,
  Modal,
  PanResponder,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { theme, spacing, radii } from "@/src/lib/theme";

type Props = {
  visible: boolean;
  initialHeading: number | null | undefined;
  /** Used only for the small caption (e.g. "Cap nav" vs "Cap de dérive"). */
  contextLabel?: string;
  /** 13/07/2026 — proposer une vitesse estimée (autorités/secours) : défaut
   *  10 nds, ajustable. Le signalement passera « En navigation ». */
  speedSuggested?: boolean;
  initialSpeedKnots?: number | null;
  onClose: () => void;
  onSave: (headingDeg: number, speedKnots?: number) => Promise<void> | void;
};

const SIZE = 280;                 // diameter of the compass widget (px)
const CENTER = SIZE / 2;
const ARROW_LENGTH = CENTER - 28; // distance from center to draggable tip
const TIP_RADIUS = 22;            // touchable tip handle radius
// Ionicons "navigate" glyph naturally points ~45° up-right → subtract this
// offset so the on-screen arrow aligns with the semantic heading (0° = N up).
const NAVIGATE_ICON_OFFSET = 45;

function normalize(deg: number): number {
  const d = deg % 360;
  return d < 0 ? d + 360 : d;
}

function fmtDeg(deg: number): string {
  return `${Math.round(normalize(deg)).toString().padStart(3, "0")}°`;
}

// 16-point compass for cardinal label under the degrees readout.
const COMPASS_POINTS = [
  "N", "NNE", "NE", "ENE",
  "E", "ESE", "SE", "SSE",
  "S", "SSO", "SO", "OSO",
  "O", "ONO", "NO", "NNO",
];
function cardinal(deg: number): string {
  const idx = Math.round(normalize(deg) / 22.5) % 16;
  return COMPASS_POINTS[idx];
}

export function HeadingEditModal({
  visible,
  initialHeading,
  contextLabel,
  speedSuggested = false,
  initialSpeedKnots,
  onClose,
  onSave,
}: Props) {
  const [heading, setHeading] = useState<number>(
    typeof initialHeading === "number" ? normalize(initialHeading) : 0,
  );
  const [saving, setSaving] = useState(false);
  // Vitesse estimée (nds) — champ texte pour saisie précise + steppers ±1.
  const [speedTxt, setSpeedTxt] = useState("10");
  const initialRef = useRef<number>(
    typeof initialHeading === "number" ? normalize(initialHeading) : 0,
  );

  // Compass center in *page* coordinates — required for jitter-free drag.
  // ``locationX/Y`` from PanResponder is relative to whichever sub-view is
  // currently under the finger, which changes as we cross the ticks / tip /
  // readout and causes the saccades observed on device. Using pageX/pageY
  // and subtracting the measured center keeps deltas continuous.
  const compassRef = useRef<View>(null);
  const compassCenterPage = useRef<{ x: number; y: number } | null>(null);

  function measureCompass() {
    compassRef.current?.measureInWindow((x, y) => {
      compassCenterPage.current = { x: x + CENTER, y: y + CENTER };
    });
  }

  // Reset every time the modal opens with a fresh value.
  useEffect(() => {
    if (visible) {
      const v = typeof initialHeading === "number" ? normalize(initialHeading) : 0;
      setHeading(v);
      initialRef.current = v;
      setSaving(false);
      setSpeedTxt(
        String(
          typeof initialSpeedKnots === "number" && initialSpeedKnots > 0
            ? Math.round(initialSpeedKnots)
            : 10,
        ),
      );
      // Give the modal one frame to lay out before we measure.
      requestAnimationFrame(measureCompass);
    }
  }, [visible, initialHeading, initialSpeedKnots]);

  // PanResponder: convert touch (pageX, pageY) minus compass center into a
  // bearing. Stable across sub-views because we use page-space coordinates.
  const responder = useMemo(
    () =>
      PanResponder.create({
        onStartShouldSetPanResponder: () => true,
        onMoveShouldSetPanResponder: () => true,
        onPanResponderTerminationRequest: () => false,
        onPanResponderGrant: (e) => {
          // Refresh the center before the first move to survive rotations /
          // keyboard-driven layout shifts between opens.
          measureCompass();
          updateFromPage(e.nativeEvent.pageX, e.nativeEvent.pageY);
        },
        onPanResponderMove: (e) => {
          updateFromPage(e.nativeEvent.pageX, e.nativeEvent.pageY);
        },
      }),
    [],
  );

  function updateFromPage(pageX: number, pageY: number) {
    const c = compassCenterPage.current;
    if (!c) return;
    const dx = pageX - c.x;
    const dy = pageY - c.y;
    // atan2 gives angle from +X axis. We want bearing from North (up = -Y).
    // bearing = atan2(dx, -dy) → 0° North, clockwise.
    const rad = Math.atan2(dx, -dy);
    const deg = normalize((rad * 180) / Math.PI);
    setHeading(deg);
  }

  // Step buttons (-15° / +15°) for fine-grained adjustments.
  function step(delta: number) {
    setHeading((h) => normalize(h + delta));
  }

  function parsedSpeed(): number {
    const n = parseFloat(speedTxt.replace(",", "."));
    if (!Number.isFinite(n)) return 10;
    return Math.min(99, Math.max(0, Math.round(n)));
  }

  function bumpSpeed(delta: number) {
    setSpeedTxt(String(Math.min(99, Math.max(0, parsedSpeed() + delta))));
  }

  async function handleSave() {
    if (saving) return;
    setSaving(true);
    try {
      await onSave(
        Math.round(normalize(heading)),
        speedSuggested ? parsedSpeed() : undefined,
      );
    } finally {
      setSaving(false);
    }
  }

  // Arrow tip position for the draggable handle (UI overlay).
  const rad = (heading * Math.PI) / 180;
  const tipX = CENTER + ARROW_LENGTH * Math.sin(rad);
  const tipY = CENTER - ARROW_LENGTH * Math.cos(rad);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <Pressable style={styles.backdrop} onPress={onClose}>
        <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation()}>
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>Modifier le cap</Text>
              {contextLabel ? (
                <Text style={styles.subtitle}>{contextLabel}</Text>
              ) : null}
            </View>
            <TouchableOpacity
              onPress={onClose}
              style={styles.closeBtn}
              testID="heading-modal-close"
              hitSlop={8}
            >
              <Ionicons name="close" size={22} color={theme.textDim} />
            </TouchableOpacity>
          </View>

          {/* Compass dial — fully tactile. */}
          <View
            style={styles.compassWrap}
            {...responder.panHandlers}
            testID="heading-compass"
          >
            <View
              ref={compassRef}
              onLayout={measureCompass}
              style={styles.compassOuter}
            >
              <View style={styles.compassRing} pointerEvents="none" />
              {/* Cardinal labels */}
              <Text style={[styles.cardLabel, styles.cardN]} pointerEvents="none">N</Text>
              <Text style={[styles.cardLabel, styles.cardE]} pointerEvents="none">E</Text>
              <Text style={[styles.cardLabel, styles.cardS]} pointerEvents="none">S</Text>
              <Text style={[styles.cardLabel, styles.cardW]} pointerEvents="none">O</Text>
              {/* Tick marks every 30° */}
              {Array.from({ length: 12 }).map((_, i) => {
                const a = (i * 30 * Math.PI) / 180;
                const r1 = CENTER - 10;
                const r2 = i % 3 === 0 ? CENTER - 22 : CENTER - 16;
                const x1 = CENTER + r1 * Math.sin(a);
                const y1 = CENTER - r1 * Math.cos(a);
                const x2 = CENTER + r2 * Math.sin(a);
                const y2 = CENTER - r2 * Math.cos(a);
                const len = Math.hypot(x2 - x1, y2 - y1);
                const angDeg = (Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI;
                return (
                  <View
                    key={i}
                    pointerEvents="none"
                    style={[
                      styles.tick,
                      {
                        left: x1,
                        top: y1,
                        width: len,
                        transform: [{ rotate: `${angDeg}deg` }],
                        backgroundColor: i % 3 === 0 ? theme.primary : theme.textMute,
                        opacity: i % 3 === 0 ? 0.7 : 0.35,
                      },
                    ]}
                  />
                );
              })}

              {/* Center dot = report position. */}
              <View style={styles.centerDot} pointerEvents="none" />

              {/* Projection line (center → tip). */}
              {(() => {
                const len = Math.hypot(tipX - CENTER, tipY - CENTER);
                const angDeg = (Math.atan2(tipY - CENTER, tipX - CENTER) * 180) / Math.PI;
                return (
                  <View
                    pointerEvents="none"
                    style={[
                      styles.projection,
                      {
                        left: CENTER,
                        top: CENTER,
                        width: len,
                        transform: [{ rotate: `${angDeg}deg` }],
                      },
                    ]}
                  />
                );
              })()}

              {/* Draggable tip handle (visually). The whole dial captures
                  drag events; this handle gives a clear affordance and its
                  arrow glyph rotates to physically match the heading (like
                  a clock's minute hand). */}
              <View
                pointerEvents="none"
                style={[
                  styles.tip,
                  { left: tipX - TIP_RADIUS, top: tipY - TIP_RADIUS },
                ]}
              >
                <Ionicons
                  name="navigate"
                  size={22}
                  color={theme.bg}
                  style={{
                    transform: [{ rotate: `${heading - NAVIGATE_ICON_OFFSET}deg` }],
                  }}
                />
              </View>

              {/* Big degree readout in the middle. */}
              <View pointerEvents="none" style={styles.readout}>
                <Text style={styles.degreeText}>{fmtDeg(heading)}</Text>
                <Text style={styles.cardinalText}>{cardinal(heading)}</Text>
              </View>
            </View>
          </View>

          {/* Step buttons + reset. */}
          <View style={styles.stepRow}>
            <TouchableOpacity
              style={styles.stepBtn}
              onPress={() => step(-15)}
              testID="heading-minus-15"
              activeOpacity={0.85}
            >
              <Ionicons name="remove" size={18} color={theme.text} />
              <Text style={styles.stepText}>15°</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.stepBtn}
              onPress={() => step(-1)}
              testID="heading-minus-1"
              activeOpacity={0.85}
            >
              <Ionicons name="chevron-back" size={18} color={theme.text} />
              <Text style={styles.stepText}>1°</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.stepBtn}
              onPress={() => setHeading(initialRef.current)}
              testID="heading-reset"
              activeOpacity={0.85}
            >
              <Ionicons name="refresh" size={18} color={theme.textDim} />
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.stepBtn}
              onPress={() => step(1)}
              testID="heading-plus-1"
              activeOpacity={0.85}
            >
              <Text style={styles.stepText}>1°</Text>
              <Ionicons name="chevron-forward" size={18} color={theme.text} />
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.stepBtn}
              onPress={() => step(15)}
              testID="heading-plus-15"
              activeOpacity={0.85}
            >
              <Text style={styles.stepText}>15°</Text>
              <Ionicons name="add" size={18} color={theme.text} />
            </TouchableOpacity>
          </View>

          {/* Vitesse estimée (13/07/2026) — autorités/secours uniquement. */}
          {speedSuggested && (
            <View style={styles.speedBlock}>
              <View style={styles.speedRow}>
                <Text style={styles.speedLabel}>Vitesse estimée</Text>
                <TouchableOpacity
                  style={styles.speedStepBtn}
                  onPress={() => bumpSpeed(-1)}
                  testID="heading-speed-minus"
                  activeOpacity={0.85}
                >
                  <Ionicons name="remove" size={16} color={theme.text} />
                </TouchableOpacity>
                <TextInput
                  style={styles.speedInput}
                  value={speedTxt}
                  onChangeText={setSpeedTxt}
                  keyboardType="numeric"
                  maxLength={2}
                  selectTextOnFocus
                  testID="heading-speed-input"
                />
                <Text style={styles.speedUnit}>nds</Text>
                <TouchableOpacity
                  style={styles.speedStepBtn}
                  onPress={() => bumpSpeed(1)}
                  testID="heading-speed-plus"
                  activeOpacity={0.85}
                >
                  <Ionicons name="add" size={16} color={theme.text} />
                </TouchableOpacity>
              </View>
              <Text style={styles.speedHint}>
                Le signalement passera « En navigation » avec ce cap et cette
                vitesse (projection affichée sur la carte).
              </Text>
            </View>
          )}

          {/* Actions */}
          <View style={styles.actions}>
            <TouchableOpacity
              style={styles.cancelBtn}
              onPress={onClose}
              disabled={saving}
              testID="heading-cancel"
              activeOpacity={0.85}
            >
              <Text style={styles.cancelText}>Annuler</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.saveBtn, saving && { opacity: 0.6 }]}
              onPress={handleSave}
              disabled={saving}
              testID="heading-save"
              activeOpacity={0.85}
            >
              <Ionicons name="checkmark" size={20} color={theme.bg} />
              <Text style={styles.saveText}>
                {saving ? "Enregistrement…" : "Valider"}
              </Text>
            </TouchableOpacity>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.72)",
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.md,
  },
  sheet: {
    width: "100%",
    maxWidth: 380,
    backgroundColor: theme.bg2,
    borderRadius: radii.lg,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: theme.border,
    gap: spacing.md,
  },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  title: { color: theme.text, fontSize: 18, fontWeight: "900" },
  subtitle: { color: theme.textDim, fontSize: 12, marginTop: 2 },
  // Vitesse estimée (13/07/2026).
  speedBlock: { gap: 6 },
  speedRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  speedLabel: { color: theme.text, fontWeight: "800", fontSize: 13, flex: 1 },
  speedStepBtn: {
    width: 34, height: 34, borderRadius: 17,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.bg3, borderWidth: 1, borderColor: theme.border,
  },
  speedInput: {
    minWidth: 52, textAlign: "center",
    color: theme.text, fontSize: 18, fontWeight: "900",
    backgroundColor: theme.bg, borderWidth: 1, borderColor: theme.border,
    borderRadius: radii.sm, paddingVertical: 6, paddingHorizontal: 8,
  },
  speedUnit: { color: theme.textDim, fontWeight: "800", fontSize: 13 },
  speedHint: { color: theme.textMute, fontSize: 11, fontStyle: "italic" },
  closeBtn: {
    width: 32, height: 32, borderRadius: 16,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.bg3,
  },
  compassWrap: {
    alignItems: "center", justifyContent: "center",
    paddingVertical: spacing.sm,
  },
  compassOuter: {
    width: SIZE,
    height: SIZE,
    borderRadius: SIZE / 2,
    backgroundColor: theme.bg,
    borderWidth: 2,
    borderColor: theme.primary,
    position: "relative",
  },
  compassRing: {
    position: "absolute",
    top: 8, left: 8, right: 8, bottom: 8,
    borderRadius: (SIZE - 16) / 2,
    borderWidth: 1,
    borderColor: theme.border,
  },
  cardLabel: {
    position: "absolute",
    color: theme.textDim,
    fontWeight: "900",
    fontSize: 14,
  },
  cardN: { top: 4, left: 0, right: 0, textAlign: "center", color: theme.primary },
  cardE: { right: 8, top: CENTER - 8 },
  cardS: { bottom: 4, left: 0, right: 0, textAlign: "center" },
  cardW: { left: 8, top: CENTER - 8 },
  tick: {
    position: "absolute",
    height: 2,
    borderRadius: 1,
  },
  centerDot: {
    position: "absolute",
    left: CENTER - 7, top: CENTER - 7,
    width: 14, height: 14, borderRadius: 7,
    backgroundColor: theme.primary,
    borderWidth: 2, borderColor: theme.bg,
  },
  projection: {
    position: "absolute",
    height: 3,
    borderRadius: 2,
    backgroundColor: theme.primary,
    transformOrigin: "left center",
  },
  tip: {
    position: "absolute",
    width: TIP_RADIUS * 2,
    height: TIP_RADIUS * 2,
    borderRadius: TIP_RADIUS,
    backgroundColor: theme.primary,
    alignItems: "center", justifyContent: "center",
    borderWidth: 2, borderColor: theme.bg,
    shadowColor: "#000",
    shadowOpacity: 0.3,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
    elevation: 4,
  },
  readout: {
    position: "absolute",
    left: 0, right: 0, top: CENTER + 18,
    alignItems: "center",
  },
  degreeText: {
    color: theme.text,
    fontSize: 32,
    fontWeight: "900",
    letterSpacing: 1,
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
  },
  cardinalText: {
    color: theme.textDim,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 1,
    marginTop: 2,
  },
  stepRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    gap: 6,
  },
  stepBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
    paddingVertical: 12,
    borderRadius: radii.md,
    backgroundColor: theme.bg3,
    borderWidth: 1,
    borderColor: theme.border,
    minHeight: 44,
  },
  stepText: { color: theme.text, fontWeight: "800", fontSize: 13 },
  actions: { flexDirection: "row", gap: spacing.sm },
  cancelBtn: {
    flex: 1,
    paddingVertical: 14,
    borderRadius: radii.md,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.bg3,
    borderWidth: 1,
    borderColor: theme.border,
    minHeight: 50,
  },
  cancelText: { color: theme.text, fontWeight: "800" },
  saveBtn: {
    flex: 2,
    paddingVertical: 14,
    borderRadius: radii.md,
    alignItems: "center", justifyContent: "center",
    flexDirection: "row", gap: 6,
    backgroundColor: theme.primary,
    minHeight: 50,
  },
  saveText: { color: theme.bg, fontWeight: "900", fontSize: 15 },
});

// Animated is imported for future tween animations; suppress unused warning.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
const _AnimRef = Animated;
