import { Tabs } from "expo-router";
import Ionicons from "@expo/vector-icons/Ionicons";
import { C } from "../../../components/ui";
import { useSession } from "../../../lib/session";
export default function TabsLayout() {
  const { access } = useSession();
  const admin = access?.access_role === "PLATFORM_ADMIN";
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: C.cyan,
        tabBarInactiveTintColor: "#C2CEE0",
        tabBarStyle: { backgroundColor: C.navy, borderTopColor: C.navy },
        tabBarLabelStyle: { fontSize: 10, fontWeight: "600" },
        sceneStyle: { backgroundColor: C.bg },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Home",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="grid-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="inventory"
        options={{
          title: "Inventory",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="albums-outline" color={color} size={size} />
          ),
        }}
      />
      <Tabs.Screen
        name="scan"
        options={{
          title: "Scan",
          tabBarIcon: ({ color }) => (
            <Ionicons name="scan" color={color} size={28} />
          ),
        }}
      />
      <Tabs.Screen
        name="activity"
        options={{
          title: admin ? "To review" : "Sales",
          tabBarIcon: ({ color, size }) => (
            <Ionicons
              name={admin ? "checkbox-outline" : "receipt-outline"}
              color={color}
              size={size}
            />
          ),
        }}
      />
      <Tabs.Screen
        name="account"
        options={{
          title: "Account",
          tabBarIcon: ({ color, size }) => (
            <Ionicons name="person-circle-outline" color={color} size={size} />
          ),
        }}
      />
    </Tabs>
  );
}
