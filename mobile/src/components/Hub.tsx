import { useEffect } from "react";
import { Linking, Text, View } from "react-native";
import { HUB_ENTRY } from "../lib/hub";
import { Button, styles } from "./ui";
export default function Hub() {
  useEffect(() => {
    window.location.replace(HUB_ENTRY);
  }, []);
  return <View style={[styles.page, styles.content]}>
    <Text style={styles.title}>PullTheory</Text>
    <Text style={styles.text}>Opening your existing hub…</Text>
    <Button title="Open PullTheory" onPress={() => { void Linking.openURL(HUB_ENTRY); }} />
  </View>;
}
