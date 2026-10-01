import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { C } from "../components/ui";
import { SessionProvider } from "../lib/session";
export default function RootLayout() {
  return (
    <SessionProvider>
      <StatusBar style="dark" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: C.bg },
        }}
      />
    </SessionProvider>
  );
}
