// SignalMar — Slider CUSTOM à zone tactile GÉNÉREUSE.
// 17/07/2026 (retour terrain) — le @react-native-community/slider n'accepte
// pas d'agrandissement de sa touch-area sur Android : le doigt/gant en mer
// glisse à côté du thumb et ne bouge pas la valeur. Ce composant reproduit
// visuellement le même slider mais gère les touchers via GESTURE HANDLER
// (v1: PanResponder, v2 17/07 après retour testing : Gesture.Pan cross-web-
// et-natif) sur une zone de 64 px de haut (2× la recommandation d'acces-
// sibilité Material 48×48dp), avec TAP-TO-SEEK + drag continu.

import { useCallback, useRef, useState } from "react";
import { LayoutChangeEvent, StyleSheet, View, ViewStyle } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import { runOnJS } from "react-native-reanimated";

import { theme } from "@/src/lib/theme";

const TRACK_H = 4;
const THUMB_D = 22;
const HIT_H = 64; // Zone tactile totale (haut + bas du track)

export interface MarineSliderProps {
  value: number;
  minimumValue?: number;
  maximumValue?: number;
  step?: number;
  onValueChange?: (v: number) => void;
  onSlidingComplete?: (v: number) => void;
  minimumTrackTintColor?: string;
  maximumTrackTintColor?: string;
  thumbTintColor?: string;
  disabled?: boolean;
  style?: ViewStyle;
  testID?: string;
}

function clamp(x: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, x));
}

export function MarineSlider(props: MarineSliderProps) {
  const {
    value, minimumValue = 0, maximumValue = 1, step = 0,
    onValueChange, onSlidingComplete,
    minimumTrackTintColor = theme.primary,
    maximumTrackTintColor = theme.border,
    thumbTintColor = theme.primary,
    disabled = false, style, testID,
  } = props;

  const [w, setW] = useState(0);
  const wRef = useRef(0);
  wRef.current = w;
  // Valeur live pendant le drag (indépendante de la prop `value`).
  const [liveVal, setLiveVal] = useState<number | null>(null);
  const lastValRef = useRef(value);
  lastValRef.current = liveVal ?? value;

  const range = Math.max(1e-6, maximumValue - minimumValue);
  const displayed = clamp(liveVal ?? value, minimumValue, maximumValue);
  const pct = (displayed - minimumValue) / range;

  const applyFromX = useCallback((x: number, commit: boolean) => {
    const wCur = wRef.current;
    if (wCur <= 0) return;
    const usable = wCur - THUMB_D;
    if (usable <= 0) return;
    const localX = clamp(x - THUMB_D / 2, 0, usable);
    let v = minimumValue + (localX / usable) * range;
    if (step > 0) v = minimumValue + Math.round((v - minimumValue) / step) * step;
    v = clamp(v, minimumValue, maximumValue);
    if (Math.abs(v - lastValRef.current) < 1e-8 && !commit) return;
    lastValRef.current = v;
    setLiveVal(v);
    onValueChange?.(v);
    if (commit) {
      onSlidingComplete?.(v);
      // Après commit, on relâche le contrôle vers la prop parent (au
      // prochain render la valeur `value` reprendra la main).
      setTimeout(() => setLiveVal(null), 0);
    }
  }, [minimumValue, maximumValue, range, step, onValueChange, onSlidingComplete]);

  // ─── Gesture.Pan (RNGH) ─── activation immédiate + tap-to-seek.
  // On combine avec Gesture.Tap pour capturer le simple clic (sans drag),
  // les deux courent en parallèle.
  const tap = Gesture.Tap()
    .maxDistance(24)
    .onEnd((e) => {
      "worklet";
      if (disabled) return;
      runOnJS(applyFromX)(e.x, true);
    });
  const pan = Gesture.Pan()
    .minDistance(0)      // activation immédiate
    .activeOffsetX([-1, 1])
    .onBegin((e) => {
      "worklet";
      if (disabled) return;
      runOnJS(applyFromX)(e.x, false);
    })
    .onUpdate((e) => {
      "worklet";
      if (disabled) return;
      runOnJS(applyFromX)(e.x, false);
    })
    .onEnd((e) => {
      "worklet";
      if (disabled) return;
      runOnJS(applyFromX)(e.x, true);
    });
  const gesture = Gesture.Simultaneous(tap, pan);

  return (
    <GestureDetector gesture={gesture}>
      <View
        style={[styles.container, style, disabled && { opacity: 0.5 }]}
        testID={testID}
        onLayout={(e: LayoutChangeEvent) => setW(e.nativeEvent.layout.width)}
        collapsable={false}
      >
        {/* Rail de fond */}
        <View style={[styles.track, { backgroundColor: maximumTrackTintColor }]} />
        {/* Rail actif (rempli du min jusqu'au thumb) */}
        <View
          style={[
            styles.trackFill,
            {
              width: w > 0 ? THUMB_D / 2 + pct * (w - THUMB_D) : 0,
              backgroundColor: minimumTrackTintColor,
            },
          ]}
        />
        {/* Thumb */}
        <View
          style={[
            styles.thumb,
            {
              backgroundColor: thumbTintColor,
              left: w > 0 ? pct * (w - THUMB_D) : 0,
            },
          ]}
          pointerEvents="none"
        />
      </View>
    </GestureDetector>
  );
}

const styles = StyleSheet.create({
  container: {
    height: HIT_H,
    width: "100%",
    justifyContent: "center",
  },
  track: {
    position: "absolute",
    left: THUMB_D / 2,
    right: THUMB_D / 2,
    top: HIT_H / 2 - TRACK_H / 2,
    height: TRACK_H,
    borderRadius: TRACK_H / 2,
  },
  trackFill: {
    position: "absolute",
    left: 0,
    top: HIT_H / 2 - TRACK_H / 2,
    height: TRACK_H,
    borderRadius: TRACK_H / 2,
  },
  thumb: {
    position: "absolute",
    top: HIT_H / 2 - THUMB_D / 2,
    width: THUMB_D,
    height: THUMB_D,
    borderRadius: THUMB_D / 2,
    shadowColor: "#000",
    shadowOpacity: 0.25,
    shadowRadius: 4,
    shadowOffset: { width: 0, height: 2 },
    elevation: 3,
  },
});
