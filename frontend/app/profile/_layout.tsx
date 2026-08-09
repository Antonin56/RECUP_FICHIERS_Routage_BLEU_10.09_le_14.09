import { Stack } from "expo-router";

export default function ProfileSubLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: "#0B132B" },
      }}
    />
  );
}
