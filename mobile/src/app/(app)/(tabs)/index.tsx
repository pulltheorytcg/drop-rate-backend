import { useCallback, useState } from "react";
import { Text, View } from "react-native";
import { router } from "expo-router";
import { useSession } from "../../../lib/session";
import { useLoad } from "../../../lib/useLoad";
import { inventoryPath } from "../../../lib/workflows";
import { errorMessage } from "../../../lib/api";
import type { Inventory, Page as PageType } from "../../../lib/types";
import { money, label } from "../../../lib/types";
import {
  Page,
  Panel,
  Button,
  Notice,
  CardRow,
  Empty,
  styles,
  C,
} from "../../../components/ui";
export default function Home() {
  const { api, access } = useSession();
  const admin = access!.access_role === "PLATFORM_ADMIN";
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const load = useCallback(async () => {
    const [inventory, summary, pending] = await Promise.all([
      api.request<PageType<Inventory>>(inventoryPath(access!) + "?limit=4"),
      api.request<Record<string, any>>(
        admin ? "/api/v1/inventory/readiness" : "/api/v1/owner/overview",
      ),
      api.pending(),
    ]);
    return { inventory, summary: admin ? summary : summary.summary, pending };
  }, [api, access, admin]);
  const { data, error, loading, reload } = useLoad(load);
  const resume = async () => {
    setSaving(true);
    setSaveError("");
    try {
      await api.resumeIntake();
      await reload();
    } catch (e) {
      setSaveError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };
  return (
    <Page refreshing={loading} onRefresh={() => void reload()}>
      <View style={styles.spread}>
        <Text style={styles.eyebrow}>PULLTHEORY TCG</Text>
        <Text style={{ ...styles.small, color: C.lime }}>
          {admin ? "FOUNDER HQ" : "SELLER HUB"}
        </Text>
      </View>
      <View>
        <Text style={styles.muted}>
          Welcome back, {access!.display_name.split(" ")[0]}
        </Text>
        <Text style={styles.title}>
          {admin ? "Ready for the next pull." : "Your collection, at a glance."}
        </Text>
      </View>
      <Notice error>{error || saveError}</Notice>
      {error && (
        <Button title="Try again" secondary onPress={() => void reload()} />
      )}
      {data?.pending && (
        <Panel>
          <Text style={styles.section}>Finish your last save</Text>
          <Text style={styles.muted}>
            {data.pending.title} has a pending request. Retrying keeps the same
            reference to prevent duplicates.
          </Text>
          <Button
            title="Retry pending save"
            busy={saving}
            onPress={() => void resume()}
          />
        </Panel>
      )}
      <Panel style={{ backgroundColor: "#1D2B23", borderColor: "#3B4B32" }}>
        <Text style={styles.eyebrow}>
          {admin ? "ACTIVE STOCK" : "ACTIVE MARKET VALUE"}
        </Text>
        <Text style={{ ...styles.metric, fontSize: 42 }}>
          {data
            ? admin
              ? data.summary.total
              : money(data.summary.active_market_value_minor)
            : "—"}
        </Text>
        <Text style={styles.muted}>
          {admin
            ? "Physical items linked to your owner account"
            : "Known values across your active stock; unvalued items excluded"}
        </Text>
        <View style={styles.divider} />
        <View style={styles.spread}>
          <View>
            <Text style={styles.small}>
              {admin ? "Ready / approved" : "Inventory items"}
            </Text>
            <Text style={styles.section}>
              {data
                ? admin
                  ? data.summary.approved
                  : data.summary.total_inventory_count
                : "—"}
            </Text>
          </View>
          <View>
            <Text style={styles.small}>
              {admin ? "Identity to confirm" : "Store value"}
            </Text>
            <Text style={styles.section}>
              {data
                ? admin
                  ? data.summary.identity_unconfirmed
                  : money(data.summary.active_store_value_minor)
                : "—"}
            </Text>
          </View>
        </View>
      </Panel>
      <Button
        title="Scan a card or sealed product"
        icon="scan"
        onPress={() => router.push("/(app)/(tabs)/scan")}
      />
      <View style={styles.spread}>
        <Text style={styles.section}>Recently updated</Text>
        <Text
          onPress={() => router.push("/(app)/(tabs)/inventory")}
          accessibilityRole="link"
          style={{ color: C.lime, padding: 10 }}
        >
          View all →
        </Text>
      </View>
      {data?.inventory.items.length ? (
        <Panel>
          {data.inventory.items.map((item) => (
            <CardRow
              key={item.inventory_code}
              card={{
                ...item,
                image_url: item.image_url || item.card_image_direct_url,
              }}
              subtitle={label(item.status)}
              trailing={money(item.market_value_minor)}
              onPress={() =>
                router.push({
                  pathname: "/(app)/item",
                  params: { code: item.inventory_code },
                })
              }
            />
          ))}
        </Panel>
      ) : !loading && !error ? (
        <Empty
          title="Your inventory starts here"
          detail="Scan an item to create a draft for review."
        />
      ) : null}
      <Text style={styles.small}>
        Each entry represents one physical item. Recognition suggestions always
        need your confirmation.
      </Text>
    </Page>
  );
}
