// Phase K — Modale de configuration du CÔNE navigation (angle + distance).
// Découpé de map.tsx le 26/08/2026 : déplacement PUR, aucun changement.
import { Modal, Pressable, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import Slider from "@react-native-community/slider";

import { theme } from "@/src/lib/theme";
import { ZoneField, NAV_SLIDER_MAX_KM, NAV_INPUT_MAX_KM } from "@/src/components/AlertSettingsPanel";
import { CONE_ANGLE_MAX, CONE_ANGLE_MIN } from "@/src/screens/map/map-constants";
import { styles } from "@/src/screens/map/map-styles";

interface Props {
  visible: boolean;
  coneAngleDeg: number;
  setConeAngleDeg: (deg: number) => void;
  zoneNavM: number;
  onCommitZoneNavM: (m: number) => void;
  onClose: () => void;
}

export function ConeConfigModal({
  visible, coneAngleDeg, setConeAngleDeg, zoneNavM, onCommitZoneNavM, onClose,
}: Props) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable style={styles.sheetBackdrop} onPress={onClose}>
        <Pressable style={styles.sheet} onPress={(e) => e.stopPropagation?.()}>
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHeader}>
            <View style={{ flex: 1 }}>
              <Text style={styles.sheetTitle}>Cône Navigation</Text>
              <Text style={styles.sheetSubtitle}>
                Reste focus sur les signalements devant toi.
              </Text>
            </View>
            <TouchableOpacity onPress={onClose} testID="map-cone-close">
              <Ionicons name="close" size={22} color={theme.text} />
            </TouchableOpacity>
          </View>

          {/* Phase K — Live preview of the double-cone shape (flare +
              corridor). Boat is at the bottom apex; the shape opens
              upward. The corridor rectangle above the flare uses the same
              width as the flare's base, exactly like on the map. */}
          {(() => {
            const halfDeg = coneAngleDeg / 2;
            // Flare = 40 px tall, its base width scales with tan(halfAngle).
            const flareHeightPx = 40;
            const halfWidthPx = Math.max(6, flareHeightPx * Math.tan((halfDeg * Math.PI) / 180));
            const corridorWidthPx = halfWidthPx * 2;
            const corridorHeightPx = 78;
            return (
              <View style={styles.conePreviewBox}>
                <View style={{ alignItems: "center", justifyContent: "flex-end", flex: 1, paddingBottom: 4 }}>
                  <View style={[
                    styles.conePreviewCorridor,
                    { width: corridorWidthPx, height: corridorHeightPx },
                  ]} />
                  <View style={[
                    styles.conePreviewFlare,
                    {
                      borderLeftWidth: halfWidthPx,
                      borderRightWidth: halfWidthPx,
                      borderTopWidth: flareHeightPx,
                    },
                  ]} />
                  <View style={styles.conePreviewBoatDot} />
                </View>
                <Text style={styles.conePreviewLabel}>{coneAngleDeg}°</Text>
                <Text style={styles.conePreviewDim}>
                  évasement 1.0 km · corridor {(2 * 1 * Math.sin((halfDeg * Math.PI) / 180)).toFixed(2)} km
                </Text>
              </View>
            );
          })()}

          <View style={styles.coneSliderRow}>
            <Text style={styles.sheetSection}>Angle du cône</Text>
            <Text style={styles.coneSliderValue}>{coneAngleDeg}°</Text>
          </View>
          <Slider
            testID="map-cone-slider"
            style={styles.coneSlider}
            minimumValue={CONE_ANGLE_MIN}
            maximumValue={CONE_ANGLE_MAX}
            step={1}
            value={coneAngleDeg}
            onValueChange={(v) => setConeAngleDeg(Math.round(v))}
            minimumTrackTintColor="#F4A261"
            maximumTrackTintColor={theme.border}
            thumbTintColor="#F4A261"
          />
          <View style={styles.coneSliderScale}>
            <Text style={styles.coneSliderScaleText}>{CONE_ANGLE_MIN}°</Text>
            <Text style={styles.coneSliderScaleText}>{CONE_ANGLE_MAX}°</Text>
          </View>

          {/* 15/07/2026 (demande user) — distance du cône réglable ICI,
              sans passer par la page Réglages. Même réglage que « Zone de
              veille — Navigation » (zoneNavM), mêmes bornes. */}
          <View style={styles.coneDistanceBlock}>
            <ZoneField
              icon="navigate"
              label="Distance du cône"
              hint=""
              valueM={zoneNavM}
              onCommitM={onCommitZoneNavM}
              testIDPrefix="map-cone-distance"
              showHint={false}
              sliderMaxKm={NAV_SLIDER_MAX_KM}
              inputMaxKm={NAV_INPUT_MAX_KM}
            />
          </View>

          <View style={styles.coneInfoRow}>
            <Ionicons name="information-circle-outline" size={16} color={theme.textDim} />
            <Text style={styles.coneInfoText}>
              Évasement fixe 1 km, puis corridor parallèle (largeur constante) jusqu&apos;à la distance choisie.{"\n"}
              Signalements HORS corridor : grisés à 30 % (visibles mais non-alertants).
            </Text>
          </View>

          <TouchableOpacity style={styles.sheetApply} onPress={onClose} testID="map-cone-apply">
            <Text style={styles.sheetApplyText}>Terminé</Text>
          </TouchableOpacity>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
