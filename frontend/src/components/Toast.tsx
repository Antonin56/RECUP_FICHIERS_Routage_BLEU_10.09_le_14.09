import { useEffect, useState, type ReactNode } from "react";
import {
  Animated,
  StyleSheet,
  Text,
  View,
  TouchableOpacity,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { theme, spacing, radii } from "@/src/lib/theme";

type ToastType = "info" | "success" | "error";
type ToastItem = { id: number; type: ToastType; message: string };

let pushFn: ((t: ToastType, m: string) => void) | null = null;

export function showToast(type: ToastType, message: string) {
  pushFn?.(type, message);
}

export function ToastHost({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  useEffect(() => {
    pushFn = (type, message) => {
      const id = Date.now() + Math.random();
      setItems((prev) => [...prev, { id, type, message }]);
      setTimeout(() => {
        setItems((prev) => prev.filter((t) => t.id !== id));
      }, 3500);
    };
    return () => {
      pushFn = null;
    };
  }, []);

  return (
    <View style={{ flex: 1 }}>
      {children}
      <View
        pointerEvents="box-none"
        style={[styles.host, Platform.OS === "web" && { position: "fixed" as never }]}
      >
        {items.map((t) => (
          <ToastItem
            key={t.id}
            item={t}
            onPress={() => setItems((prev) => prev.filter((x) => x.id !== t.id))}
          />
        ))}
      </View>
    </View>
  );
}

function ToastItem({ item, onPress }: { item: ToastItem; onPress: () => void }) {
  const opacity = useState(new Animated.Value(0))[0];
  useEffect(() => {
    Animated.timing(opacity, { toValue: 1, duration: 200, useNativeDriver: true }).start();
  }, [opacity]);
  const bg =
    item.type === "success"
      ? theme.success
      : item.type === "error"
        ? theme.danger
        : theme.bg2;
  const icon =
    item.type === "success"
      ? "checkmark-circle"
      : item.type === "error"
        ? "alert-circle"
        : "information-circle";
  return (
    <Animated.View style={{ opacity }}>
      <TouchableOpacity
        activeOpacity={0.9}
        onPress={onPress}
        testID="toast"
        style={[styles.toast, { backgroundColor: bg }]}
      >
        <Ionicons name={icon} size={20} color="#fff" />
        <Text style={styles.text}>{item.message}</Text>
      </TouchableOpacity>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  host: {
    position: "absolute",
    top: spacing.xxl,
    left: spacing.md,
    right: spacing.md,
    gap: spacing.sm,
    zIndex: 9999,
  },
  toast: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: 12,
    paddingHorizontal: spacing.md,
    borderRadius: radii.md,
    shadowColor: "#000",
    shadowOpacity: 0.4,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 6,
  },
  text: { color: "#fff", fontWeight: "700", flex: 1 },
});
