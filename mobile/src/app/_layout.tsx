import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { C } from "../components/ui";
export default function RootLayout() {
  return <>
    <StatusBar style="dark" />
    <Stack screenOptions={{headerShown: false, contentStyle: {backgroundColor: C.bg}}} />
  </>;
}
