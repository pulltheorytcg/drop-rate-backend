import { useCallback, useState } from "react";
import { Text, View } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useSession } from "../../lib/session";
import { useLoad } from "../../lib/useLoad";
import { inventoryPath } from "../../lib/workflows";
import { errorMessage } from "../../lib/api";
import type { Inventory, Page as PageType } from "../../lib/types";
import { money, label, minorUnits } from "../../lib/types";
import {
  Page,
  Panel,
  Button,
  Field,
  Notice,
  CardArt,
  styles,
  C,
} from "../../components/ui";
export default function ItemScreen() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const { api, access } = useSession();
  const admin = access!.access_role === "PLATFORM_ADMIN";
  const load = useCallback(async () => {
    const page = await api.request<PageType<Inventory>>(
      `${inventoryPath(access!)}?search=${encodeURIComponent(code)}&limit=100`,
    );
    const item = page.items.find((i) => i.inventory_code === code);
    if (!item) throw new Error("This inventory item could not be found.");
    return item;
  }, [api, access, code]);
  const { data: item, error, loading, reload } = useLoad(load);
  const [draftCost, setCost] = useState<string>();
  const [draftPrice, setPrice] = useState<string>();
  const [draftNotes, setNotes] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [saveError, setSaveError] = useState("");
  const cost =
    draftCost ??
    (item?.acquisition_cost_minor == null
      ? ""
      : (item.acquisition_cost_minor / 100).toFixed(2));
  const price =
    draftPrice ??
    (item?.store_price_minor == null
      ? ""
      : (item.store_price_minor / 100).toFixed(2));
  const notes = draftNotes ?? item?.notes ?? "";
  const save = async () => {
    if (!admin || !item?.id || !item.version) return;
    setBusy(true);
    setSaveError("");
    setMessage("");
    try {
      const priceValue = minorUnits(price);
      if (priceValue !== null && priceValue < 100)
        throw new Error("Store price must be at least £1.00.");
      await api.request(`/api/v1/inventory/${item.id}`, "PATCH", {
        version: item.version,
        acquisition_cost_minor: minorUnits(cost),
        store_price_minor: priceValue,
        notes,
      });
      setMessage("Changes saved.");
      await reload();
      setCost(undefined);
      setPrice(undefined);
      setNotes(undefined);
    } catch (e) {
      setSaveError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Page refreshing={loading} onRefresh={() => void reload()}>
      <Notice error>{error || saveError}</Notice>
      <Notice>{message}</Notice>
      {error && (
        <Button title="Reload item" secondary onPress={() => void reload()} />
      )}{" "}
      {item && (
        <>
          <View style={{ alignItems: "center", gap: 12 }}>
            <CardArt
              card={{
                ...item,
                image_url: item.image_url || item.card_image_direct_url,
              }}
              size={160}
            />
            <Text style={{ ...styles.title, textAlign: "center" }}>
              {item.name}
            </Text>
            <Text style={styles.muted}>{item.inventory_code}</Text>
            <Text style={{ color: C.lime }}>{label(item.status)}</Text>
          </View>
          <Panel>
            {[
              ["Set", item.set_name],
              ["Card number", item.card_number],
              ["Variant", item.variant],
              ["Language", item.language],
              [
                "Condition / grade",
                item.grading_company
                  ? `${item.grading_company} ${item.grade}`
                  : item.seal_status || item.condition,
              ],
              ["Market value", money(item.market_value_minor)],
              ["Store price", money(item.store_price_minor)],
            ].map(([k, v]) => (
              <View key={k} style={styles.spread}>
                <Text style={styles.muted}>{k}</Text>
                <Text style={{ ...styles.text, flex: 1, textAlign: "right" }}>
                  {v || "Not recorded"}
                </Text>
              </View>
            ))}
          </Panel>
          {admin && (
            <Panel>
              <Text style={styles.section}>Stock details</Text>
              <Text style={styles.muted}>
                Location:{" "}
                {item.storage_location_label || item.location || "Not recorded"}
              </Text>
              <Field
                label="Acquisition cost (£) — blank if unknown"
                keyboardType="decimal-pad"
                value={cost}
                onChangeText={setCost}
              />
              <Field
                label="Store price (£)"
                keyboardType="decimal-pad"
                value={price}
                onChangeText={setPrice}
              />
              <Field
                label="Notes"
                multiline
                value={notes}
                onChangeText={setNotes}
                maxLength={2000}
              />
              <Button
                title="Save stock details"
                busy={busy}
                disabled={loading}
                onPress={() => void save()}
              />
              <Text style={styles.small}>
                Changes are checked against the current item version. Complete
                identity, media, location and publication reviews in Founder HQ.
              </Text>
            </Panel>
          )}
        </>
      )}
    </Page>
  );
}
