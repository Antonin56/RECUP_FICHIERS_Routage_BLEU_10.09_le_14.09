/**
 * SignalMar — Section accordéon de la page Réglages (20/07/2026, choix
 * armateur : familles repliables sur une seule page). Gros en-tête tapable
 * (utilisable avec des gants), chevron animé implicite, une seule section
 * ouverte à la fois (géré par le parent).
 */
import type { ReactNode } from "react";
import { StyleSheet, Text, TouchableOpacity, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { radii, spacing, theme } from "@/src/lib/theme";

export function AccordionSection(props: {
  icon: keyof typeof Ionicons.glyphMap;
  iconColor?: string;
  title: string;
  subtitle?: string;
  open: boolean;
  onToggle: () => void;
  children: ReactNode;
  testID?: string;
}) {
  const { icon, iconColor = theme.primary, title, subtitle, open, onToggle, children, testID } = props;
  return (
    <View style={[styles.wrap, open && styles.wrapOpen]}>
      <TouchableOpacity style={styles.header} onPress={onToggle} activeOpacity={0.85} testID={testID}>
        <View style={[styles.iconBadge, { borderColor: iconColor }]}>
          <Ionicons name={icon} size={18} color={iconColor} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>{title}</Text>
          {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
        </View>
        <Ionicons name={open ? "chevron-up" : "chevron-down"} size={20} color={theme.textMute} />
      </TouchableOpacity>
      {open ? <View style={styles.body}>{children}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    backgroundColor: theme.bg2, borderRadius: radii.md,
    borderWidth: 1, borderColor: theme.border, overflow: "hidden",
  },
  wrapOpen: { borderColor: "rgba(72,202,228,0.45)" },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: spacing.md, minHeight: 60,
  },
  iconBadge: {
    width: 34, height: 34, borderRadius: 17, borderWidth: 1,
    alignItems: "center", justifyContent: "center",
    backgroundColor: theme.bg3,
  },
  title: { color: theme.text, fontSize: 15, fontWeight: "800" },
  subtitle: { color: theme.textDim, fontSize: 11, marginTop: 2 },
  body: {
    padding: spacing.md, paddingTop: 4, gap: spacing.sm,
    borderTopWidth: 1, borderTopColor: theme.border,
  },
});
