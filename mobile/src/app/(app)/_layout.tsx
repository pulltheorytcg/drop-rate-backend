import { Stack, Redirect } from "expo-router";
import { View, Text, Platform, ActivityIndicator } from "react-native";
import { useSession } from "../../lib/session";
import { C } from "../../components/ui";
import { SafeAreaView } from "react-native-safe-area-context";
export default function AppLayout() {
  const { access, loading, demo } = useSession();
  if (loading)
    return (
      <View
        style={{ flex: 1, backgroundColor: C.bg, justifyContent: "center" }}
      >
        <ActivityIndicator color={C.lime} />
      </View>
    );
  if (!access) return <Redirect href="/sign-in" />;
  return (
    <SafeAreaView edges={["top"]} style={{ flex: 1, backgroundColor: C.bg }}>
      {(demo || Platform.OS === "web") && (
        <Text
          style={{
            textAlign: "center",
            backgroundColor: demo ? "#303A22" : "#252A35",
            color: C.lime,
            fontSize: 11,
            padding: 7,
          }}
        >
          {demo
            ? "DEMO · Sample data · No changes to your business"
            : "BROWSER PREVIEW · Session and pending saves last until this tab reloads"}
        </Text>
      )}
      <Stack
        key={`${access.user_id}:${access.owner_id}:${access.access_role}:${demo}`}
        screenOptions={{
          headerStyle: { backgroundColor: C.bg },
          headerTintColor: C.text,
          contentStyle: { backgroundColor: C.bg },
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="item" options={{ title: "Inventory details" }} />
      </Stack>
    </SafeAreaView>
  );
}
