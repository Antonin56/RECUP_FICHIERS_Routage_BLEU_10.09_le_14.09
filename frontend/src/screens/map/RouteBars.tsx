// Barres de bas d'écran de la carte : route MANUELLE (22/07), ÉDITION de
// route (26/07, règle armateur 11/08 : un seul waypoint), choix du DÉPART
// d'une route (20/07, marée 22/07) et placement d'un POINT (signalement /
// repositionnement). Découpé de map.tsx le 26/08/2026 : déplacement PUR.
import { ActivityIndicator, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { theme } from "@/src/lib/theme";
import { styles } from "@/src/screens/map/map-styles";

// ── 22/07 — barre de création de route MANUELLE (appui long = étape) ──────
export function ManualRouteBar({ insetsBottom, count, busy, onCancel, onUndo, onCreate }: {
  insetsBottom: number; count: number; busy: boolean;
  onCancel: () => void; onUndo: () => void; onCreate: () => void;
}) {
  return (
    <View style={[styles.pickBar, { paddingBottom: insetsBottom + 12 }]} testID="manual-route-bar">
      <View style={styles.pickTitleRow}>
        <Ionicons name="create" size={20} color="#2EC4B6" />
        <Text style={styles.pickTitle}>
          Route manuelle — {count} point{count > 1 ? "s" : ""}. Appui long sur la carte pour ajouter une étape.
        </Text>
      </View>
      <View style={styles.pickActions}>
        <TouchableOpacity style={styles.pickCancel} onPress={onCancel} testID="manual-route-cancel">
          <Ionicons name="close" size={20} color={theme.text} />
          <Text style={styles.pickCancelText}>Annuler</Text>
        </TouchableOpacity>
        {count > 1 && (
          <TouchableOpacity style={styles.pickCancel} onPress={onUndo} testID="manual-route-undo">
            <Ionicons name="arrow-undo" size={20} color={theme.text} />
            <Text style={styles.pickCancelText}>Retirer</Text>
          </TouchableOpacity>
        )}
        <TouchableOpacity
          style={[styles.pickContinue, (count < 2 || busy) && { opacity: 0.5 }]}
          onPress={onCreate}
          disabled={count < 2 || busy}
          testID="manual-route-create"
        >
          {busy ? (
            <ActivityIndicator color={theme.bg} />
          ) : (
            <>
              <Ionicons name="checkmark" size={20} color={theme.bg} />
              <Text style={styles.pickContinueText}>Créer cette route</Text>
            </>
          )}
        </TouchableOpacity>
      </View>
    </View>
  );
}

// ── 26/07 — barre d'ÉDITION de route (11/08 : un seul waypoint éditable) ──
export function RouteEditBar({ insetsBottom, editIdx, busy, moved, onCancel, onSave }: {
  insetsBottom: number; editIdx: number | null; busy: boolean; moved: boolean;
  onCancel: () => void; onSave: () => void;
}) {
  return (
    <View style={[styles.pickBar, { paddingBottom: insetsBottom + 12 }]} testID="route-edit-bar">
      <View style={styles.pickTitleRow}>
        <Ionicons name="move" size={20} color="#2EC4B6" />
        <Text style={styles.pickTitle}>
          {editIdx != null
            ? `Waypoint ${editIdx + 1} sélectionné — déplacez-le pour un ajustement fin (appui long ailleurs sur le tracé pour changer de waypoint).`
            : "Appui long sur le tracé pour sélectionner le waypoint à ajuster."}
        </Text>
      </View>
      <View style={styles.pickActions}>
        <TouchableOpacity style={styles.pickCancel} onPress={onCancel} testID="route-edit-cancel">
          <Ionicons name="close" size={20} color={theme.text} />
          <Text style={styles.pickCancelText}>Annuler</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.pickContinue, (busy || !moved) && { opacity: 0.5 }]}
          onPress={onSave}
          disabled={busy || !moved}
          testID="route-edit-save"
        >
          {busy ? (
            <ActivityIndicator color={theme.bg} />
          ) : (
            <>
              <Ionicons name="refresh" size={20} color={theme.bg} />
              <Text style={styles.pickContinueText}>Recalculer la route</Text>
            </>
          )}
        </TouchableOpacity>
      </View>
    </View>
  );
}

// ── 20/07 — « Créer une route » : barre de choix du DÉPART (+ marée 22/07) ─
export function RoutePickBar({ insetsBottom, pickedPoint, tideChoice, onTideChoice, onCancel, onConfirm }: {
  insetsBottom: number; pickedPoint: { lat: number; lng: number };
  tideChoice: number | null; onTideChoice: (v: number | null) => void;
  onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <View style={[styles.pickBar, { paddingBottom: insetsBottom + 12 }]} testID="route-pick-bar">
      <View style={styles.pickTitleRow}>
        <Ionicons name="git-branch" size={20} color="#2EC4B6" />
        <Text style={styles.pickTitle}>Glissez la carte pour placer le DÉPART de la route</Text>
      </View>
      <Text style={styles.pickCoords}>
        {pickedPoint.lat.toFixed(5)}°, {pickedPoint.lng.toFixed(5)}°
      </Text>
      {/* 22/07 (GO armateur) — MARÉE à l'heure de départ : Sans = marée
          basse (sécuritaire) ; sinon hauteur d'eau MINIMALE sur la durée
          estimée du trajet à partir de l'heure choisie. */}
      <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
        <Ionicons name="water" size={14} color="#48CAE4" />
        <Text style={{ color: theme.textMute, fontSize: 11, fontWeight: "800" }}>Marée :</Text>
        {([
          [null, "Sans"],
          [0, "Départ maintenant"],
          [2, "+2 h"],
          [4, "+4 h"],
          [6, "+6 h"],
        ] as [number | null, string][]).map(([v, label]) => {
          const active = tideChoice === v;
          return (
            <TouchableOpacity
              key={label}
              style={[
                styles.chip,
                { height: 30, paddingHorizontal: 10 },
                active && { backgroundColor: "#48CAE4", borderColor: "#48CAE4" },
              ]}
              onPress={() => onTideChoice(v)}
              testID={`route-tide-${v == null ? "off" : v}`}
            >
              <Text style={[styles.chipText, { fontSize: 11 }, active && { color: "#0B132B" }]}>{label}</Text>
            </TouchableOpacity>
          );
        })}
      </View>
      <View style={styles.pickActions}>
        <TouchableOpacity style={styles.pickCancel} onPress={onCancel} testID="route-pick-cancel">
          <Ionicons name="close" size={20} color={theme.text} />
          <Text style={styles.pickCancelText}>Annuler</Text>
        </TouchableOpacity>
        <TouchableOpacity style={styles.pickContinue} onPress={onConfirm} testID="route-pick-confirm">
          <Ionicons name="checkmark" size={20} color={theme.bg} />
          <Text style={styles.pickContinueText}>Calculer la route</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
}

// ── Placement d'un POINT : signalement ou repositionnement (proposition
//    communautaire / auteur) ───────────────────────────────────────────────
export function PickPlaceBar({
  insetsBottom, pickedPoint, shiftMode, authorShiftMode, busy, onCancel, onConfirm,
}: {
  insetsBottom: number; pickedPoint: { lat: number; lng: number };
  shiftMode: boolean; authorShiftMode: boolean; busy: boolean;
  onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <View style={[styles.pickBar, { paddingBottom: insetsBottom + 12 }]}>
      <View style={styles.pickTitleRow}>
        <Ionicons
          name={shiftMode ? "swap-horizontal" : "add-circle"}
          size={20}
          color={shiftMode ? theme.warning : theme.danger}
        />
        <Text style={styles.pickTitle}>
          {shiftMode
            ? (authorShiftMode
                ? "Glissez la carte pour repositionner votre signalement"
                : "Glissez la carte vers la vraie position")
            : "Faites glisser la carte pour placer le point"}
        </Text>
      </View>
      <Text style={styles.pickCoords}>
        {pickedPoint.lat.toFixed(5)}°, {pickedPoint.lng.toFixed(5)}°
      </Text>
      <View style={styles.pickActions}>
        <TouchableOpacity
          style={styles.pickCancel}
          onPress={onCancel}
          disabled={busy}
          testID="pick-cancel"
        >
          <Ionicons name="close" size={20} color={theme.text} />
          <Text style={styles.pickCancelText}>Annuler</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.pickContinue, busy && { opacity: 0.6 }]}
          onPress={onConfirm}
          disabled={busy}
          testID="pick-continue"
        >
          {busy ? (
            <ActivityIndicator color={theme.bg} />
          ) : (
            <>
              <Ionicons name="checkmark" size={20} color={theme.bg} />
              <Text style={styles.pickContinueText}>
                {shiftMode
                  ? (authorShiftMode ? "Modifier mon point" : "Proposer ce point")
                  : "Signaler ici"}
              </Text>
            </>
          )}
        </TouchableOpacity>
      </View>
    </View>
  );
}
