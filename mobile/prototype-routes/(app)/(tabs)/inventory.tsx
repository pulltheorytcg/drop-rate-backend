import { useCallback, useState } from "react";
import { Text, View, Pressable } from "react-native";
import { router } from "expo-router";
import { useSession } from "../../../lib/session";
import { useLoad } from "../../../lib/useLoad";
import { inventoryPath } from "../../../lib/workflows";
import type { Inventory, Page as PageType } from "../../../lib/types";
import { money, label } from "../../../lib/types";
import {
  Page,
  Panel,
  Field,
  Button,
  CardRow,
  Notice,
  Empty,
  styles,
  C,
} from "../../../components/ui";
export default function InventoryScreen() {
  const { api, access } = useSession();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const load = useCallback(
    () =>
      api.request<PageType<Inventory>>(
        `${inventoryPath(access!)}?limit=30&offset=${offset}&search=${encodeURIComponent(search)}&status=${status}`,
      ),
    [api, access, offset, search, status],
  );
  const { data, error, loading, reload } = useLoad(load);
  const submit = () => {
    setSearch(query.trim());
    setOffset(0);
  };
  return (
    <Page refreshing={loading} onRefresh={() => void reload()}>
      <View>
        <Text style={styles.eyebrow}>YOUR PHYSICAL COLLECTION</Text>
        <Text style={styles.title}>Inventory</Text>
      </View>
      <Field
        label="Search inventory"
        placeholder="Name, number or inventory code"
        value={query}
        onChangeText={setQuery}
        onSubmitEditing={submit}
        returnKeyType="search"
      />
      <Button title="Search" secondary onPress={submit} />
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
        {["", "DRAFT", "INSPECTION", "APPROVED", "SOLD"].map((s) => (
          <Pressable
            key={s}
            accessibilityRole="button"
            accessibilityState={{ selected: status === s }}
            onPress={() => {
              setStatus(s);
              setOffset(0);
            }}
            style={{
              padding: 11,
              borderRadius: 30,
              backgroundColor: status === s ? C.accent : C.panel,
            }}
          >
            <Text
              style={{
                color: status === s ? C.onAccent : C.muted,
                fontSize: 12,
                fontWeight: "600",
              }}
            >
              {s ? label(s) : "All items"}
            </Text>
          </Pressable>
        ))}
      </View>
      <Notice error>{error}</Notice>
      {error && (
        <Button title="Try again" secondary onPress={() => void reload()} />
      )}
      <Text style={styles.muted}>
        {loading ? "Loading inventory…" : `${data?.total ?? 0} items`}
      </Text>
      {data?.items.length ? (
        <Panel>
          {data.items.map((item) => (
            <CardRow
              key={item.inventory_code}
              card={{
                ...item,
                image_url: item.image_url || item.card_image_direct_url,
              }}
              subtitle={`${label(item.status)} · ${item.inventory_code}`}
              trailing={money(
                item.store_price_minor ?? item.recommended_retail_minor,
              )}
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
          title="No matching items"
          detail="Try another search or scan a card to start your inventory."
        />
      ) : null}
      <View style={styles.row}>
        <View style={{ flex: 1 }}>
          <Button
            title="Previous"
            secondary
            disabled={offset === 0 || loading}
            onPress={() => setOffset(Math.max(0, offset - 30))}
          />
        </View>
        <View style={{ flex: 1 }}>
          <Button
            title="Next"
            secondary
            disabled={
              loading || !data || offset + data.items.length >= data.total
            }
            onPress={() => setOffset(offset + 30)}
          />
        </View>
      </View>
    </Page>
  );
}
