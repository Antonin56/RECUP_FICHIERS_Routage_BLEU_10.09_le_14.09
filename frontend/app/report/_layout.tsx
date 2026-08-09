import { Stack } from "expo-router";
import { theme } from "@/src/lib/theme";

export default function ReportLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: theme.bg },
        animation: "slide_from_bottom",
        presentation: "modal",
      }}
    />
  );
}
