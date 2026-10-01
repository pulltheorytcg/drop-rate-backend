import { useState } from "react";
import {
  View,
  Text,
  KeyboardAvoidingView,
  Platform,
  Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Redirect } from "expo-router";
import Ionicons from "@expo/vector-icons/Ionicons";
import { useSession } from "../lib/session";
import { errorMessage, DEFAULT_BASE } from "../lib/api";
import {
  Page,
  Panel,
  Button,
  Field,
  Notice,
  C,
  styles,
} from "../components/ui";
export default function SignIn() {
  const session = useSession();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (session.access) return <Redirect href="/(app)/(tabs)" />;
  const login = async () => {
    setBusy(true);
    setError("");
    try {
      await session.login(identifier, password);
      setPassword("");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <SafeAreaView style={styles.page}>
      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <Page>
          <View style={{ paddingTop: 26, gap: 18 }}>
            <View style={styles.row}>
              <View
                style={{
                  backgroundColor: C.lime,
                  padding: 10,
                  borderRadius: 12,
                }}
              >
                <Ionicons name="layers" size={26} color={C.ink} />
              </View>
              <Text style={{ ...styles.eyebrow, color: C.text, fontSize: 14 }}>
                PULLTHEORY <Text style={{ color: C.lime }}>TCG</Text>
              </Text>
            </View>
            <Text style={{ ...styles.title, fontSize: 43, marginTop: 28 }}>
              Your collection.{"\n"}In your hands.
            </Text>
            <Text style={{ ...styles.muted, fontSize: 16, lineHeight: 25 }}>
              Scan, manage and follow every card.{"\n"}One place for sellers and
              your team.
            </Text>
          </View>
          <Panel>
            <Text style={styles.section}>Welcome back</Text>
            {Platform.OS === "web" && (
              <Notice>
                This browser preview uses the demos below. Sign in to your live
                account in the Android or iPhone build.
              </Notice>
            )}
            <Text style={styles.muted}>
              Sign in with your existing PullTheory account.
            </Text>
            <Field
              label="Email or username"
              editable={Platform.OS !== "web"}
              value={identifier}
              onChangeText={setIdentifier}
              autoCapitalize="none"
              autoCorrect={false}
              textContentType="username"
              autoComplete="username"
            />
            <Field
              label="Password"
              editable={Platform.OS !== "web"}
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              textContentType="password"
              autoComplete="current-password"
              onSubmitEditing={() => void login()}
            />
            <Notice error>{error || session.error}</Notice>
            <Button
              title="Sign in"
              onPress={() => void login()}
              busy={busy}
              disabled={
                !identifier.trim() || !password || Platform.OS === "web"
              }
              icon="arrow-forward"
            />
            <Button
              title="Password and account help"
              secondary
              onPress={() =>
                void Linking.openURL(DEFAULT_BASE).catch((e) =>
                  setError(errorMessage(e)),
                )
              }
            />
          </Panel>
          <Text style={styles.small}>
            Your account determines which tools you can access. Photos are sent
            for recognition only when you ask to identify a card.
          </Text>
          <View style={{ gap: 10 }}>
            <Text style={styles.eyebrow}>EXPLORE THE APP</Text>
            <View style={styles.row}>
              <View style={{ flex: 1 }}>
                <Button
                  title="Seller demo"
                  secondary
                  disabled={busy}
                  onPress={() =>
                    void session
                      .preview("OWNER")
                      .catch((e) => setError(errorMessage(e)))
                  }
                />
              </View>
              <View style={{ flex: 1 }}>
                <Button
                  title="Admin demo"
                  secondary
                  disabled={busy}
                  onPress={() =>
                    void session
                      .preview("PLATFORM_ADMIN")
                      .catch((e) => setError(errorMessage(e)))
                  }
                />
              </View>
            </View>
            <Text style={styles.small}>
              Demos use sample data and never connect to production.
            </Text>
          </View>
        </Page>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
