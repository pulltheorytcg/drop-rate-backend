import { useCallback, useState } from "react";
import { Text, Linking } from "react-native";
import { useSession } from "../../../lib/session";
import { useLoad } from "../../../lib/useLoad";
import { errorMessage, DEFAULT_BASE } from "../../../lib/api";
import {
  Page,
  Panel,
  Button,
  Field,
  Notice,
  styles,
} from "../../../components/ui";
export default function Account() {
  const { api, access, logout, demo } = useSession();
  const seller = access!.access_role === "OWNER";
  const [draftName, setName] = useState<string>();
  const [draftUsername, setUsername] = useState<string>();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(
    async () =>
      seller
        ? api.request<{
            profile: { display_name: string; username: string };
            email: string;
          }>("/api/v1/owner/profile")
        : null,
    [api, seller],
  );
  const state = useLoad(load);
  const name = draftName ?? state.data?.profile.display_name ?? "";
  const username = draftUsername ?? state.data?.profile.username ?? "";
  const save = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await api.request("/api/v1/owner/profile", "PATCH", {
        display_name: name.trim(),
        username: username.trim() || null,
      });
      await api.loadAccess();
      setMessage("Profile updated.");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Page>
      <Text style={styles.title}>Your account</Text>
      <Panel>
        <Text style={styles.eyebrow}>
          {seller ? "SELLER" : "FOUNDER / ADMINISTRATOR"}
        </Text>
        <Text style={styles.section}>{access!.display_name}</Text>
        <Text style={styles.muted}>
          {state.data?.email ||
            (demo ? "Demo account" : "Existing PullTheory account")}
        </Text>
        <Text style={styles.small}>
          Access is verified by PullTheory. Role changes must be made by an
          administrator.
        </Text>
      </Panel>
      <Notice error>{error || state.error}</Notice>
      <Notice>{message}</Notice>
      {seller && (
        <Panel>
          <Text style={styles.section}>Profile</Text>
          <Field
            label="Display name"
            value={name}
            onChangeText={setName}
            maxLength={160}
          />
          <Field
            label="Username"
            value={username}
            onChangeText={setUsername}
            autoCapitalize="none"
            autoCorrect={false}
            maxLength={30}
          />
          <Button
            title="Save profile"
            onPress={() => void save()}
            busy={busy}
            disabled={!name.trim() || state.loading}
          />
        </Panel>
      )}
      <Panel>
        <Text style={styles.section}>Account & security</Text>
        <Text style={styles.muted}>
          Manage password, account support and{" "}
          {seller ? "payout settings" : "advanced operations"} in the existing
          web portal.
        </Text>
        <Button
          title={seller ? "Open Seller Hub" : "Open Founder HQ"}
          secondary
          disabled={demo}
          icon="open-outline"
          onPress={() =>
            void Linking.openURL(DEFAULT_BASE + (seller ? "/owner" : "")).catch(
              (e) => setError(errorMessage(e)),
            )
          }
        />
      </Panel>
      <Panel>
        <Text style={styles.section}>About your data</Text>
        <Text style={styles.muted}>
          Sessions are stored securely on your phone. Card photographs are sent
          to the recognition service only after you choose Identify. A scan
          creates a draft only after your explicit review.
        </Text>
        <Text style={styles.small}>PullTheory TCG · Mobile preview 0.1.0</Text>
      </Panel>
      <Button
        title={demo ? "Exit demo" : "Sign out"}
        secondary
        onPress={() => void logout().catch((e) => setError(errorMessage(e)))}
      />
    </Page>
  );
}
