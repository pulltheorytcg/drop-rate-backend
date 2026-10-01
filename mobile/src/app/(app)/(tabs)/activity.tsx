import { useCallback, useState } from "react";
import { Text, View, Linking } from "react-native";
import { useSession } from "../../../lib/session";
import { useLoad } from "../../../lib/useLoad";
import type {
  ActionItem,
  Finance,
  Page as PageType,
  Sale,
  Payout,
} from "../../../lib/types";
import { money, label } from "../../../lib/types";
import {
  Page,
  Panel,
  Button,
  Notice,
  Empty,
  styles,
  C,
} from "../../../components/ui";
import { DEFAULT_BASE, errorMessage } from "../../../lib/api";
export default function Activity() {
  const { access } = useSession();
  return access!.access_role === "PLATFORM_ADMIN" ? (
    <AdminActivity />
  ) : (
    <SellerActivity />
  );
}
function AdminActivity() {
  const { api, demo } = useSession();
  const [offset, setOffset] = useState(0);
  const [linkError, setLinkError] = useState("");
  const load = useCallback(
    () =>
      api.request<PageType<ActionItem>>(
        `/api/v1/action-required?status=OPEN&limit=30&offset=${offset}`,
      ),
    [api, offset],
  );
  const { data, error, loading, reload } = useLoad(load);
  return (
    <Page refreshing={loading} onRefresh={() => void reload()}>
      <View>
        <Text style={styles.eyebrow}>FOUNDER HQ</Text>
        <Text style={styles.title}>Action Required</Text>
        <Text style={styles.muted}>
          Issues for your account, ordered by priority.
        </Text>
      </View>
      <Notice error>{error || linkError}</Notice>
      {error && (
        <Button title="Retry" secondary onPress={() => void reload()} />
      )}
      <Text style={styles.muted}>{data?.total ?? "—"} open items</Text>
      {data?.items.map((i) => (
        <Panel key={i.id}>
          <Text
            style={{
              ...styles.eyebrow,
              color:
                i.severity === "HIGH" || i.severity === "CRITICAL"
                  ? C.danger
                  : C.accent,
            }}
          >
            {label(i.severity)} · {label(i.category)}
          </Text>
          <Text style={styles.section}>{i.title}</Text>
          <Text style={styles.muted}>{i.detail}</Text>
          <Text style={styles.text}>{i.recommended_action}</Text>
        </Panel>
      ))}
      {data?.items.length === 0 && (
        <Empty
          title="All caught up"
          detail="No open issues were returned for this account."
        />
      )}
      <View style={styles.row}>
        <View style={{ flex: 1 }}>
          <Button
            title="Previous"
            secondary
            disabled={!offset || loading}
            onPress={() => setOffset(Math.max(0, offset - 30))}
          />
        </View>
        <View style={{ flex: 1 }}>
          <Button
            title="Next"
            secondary
            disabled={
              !data || offset + data.items.length >= data.total || loading
            }
            onPress={() => setOffset(offset + 30)}
          />
        </View>
      </View>
      <Button
        title="Open Founder HQ"
        secondary
        disabled={demo}
        icon="open-outline"
        onPress={() =>
          void Linking.openURL(DEFAULT_BASE).catch((e) =>
            setLinkError(errorMessage(e)),
          )
        }
      />
      <Text style={styles.small}>
        Detailed media review and publishing open in your browser, where you may
        need to sign in again.
      </Text>
    </Page>
  );
}
function SellerActivity() {
  const { api, demo } = useSession();
  const [offset, setOffset] = useState(0);
  const [linkError, setLinkError] = useState("");
  const load = useCallback(async () => {
    const [summary, sales, payouts] = await Promise.all([
      api.request<Finance>("/api/v1/owner/finance/summary"),
      api.request<PageType<Sale>>(
        `/api/v1/owner/finance/sales?limit=20&offset=${offset}`,
      ),
      api.request<{ items: Payout[] }>("/api/v1/owner/finance/payouts"),
    ]);
    return { summary, sales, payouts };
  }, [api, offset]);
  const { data, error, loading, reload } = useLoad(load);
  return (
    <Page refreshing={loading} onRefresh={() => void reload()}>
      <View>
        <Text style={styles.eyebrow}>SELLER HUB</Text>
        <Text style={styles.title}>Sales & payouts</Text>
      </View>
      <Notice error>{error || linkError}</Notice>
      {error && (
        <Button title="Retry" secondary onPress={() => void reload()} />
      )}
      <Panel>
        <Text style={styles.muted}>Available to withdraw</Text>
        <Text style={styles.metric}>
          {data
            ? money(
                data.summary.available_to_withdraw_minor,
                data.summary.currency,
              )
            : "—"}
        </Text>
        <View style={styles.spread}>
          <Text style={styles.muted}>Pending</Text>
          <Text style={styles.text}>
            {data
              ? money(data.summary.pending_minor, data.summary.currency)
              : "—"}
          </Text>
        </View>
        <View style={styles.spread}>
          <Text style={styles.muted}>Paid out</Text>
          <Text style={styles.text}>
            {data
              ? money(data.summary.paid_out_minor, data.summary.currency)
              : "—"}
          </Text>
        </View>
        {data && !data.summary.financials_complete && (
          <Notice>Some sales are still awaiting reconciliation.</Notice>
        )}
      </Panel>
      <Text style={styles.section}>Sales history</Text>
      {data?.sales.items.map((i) => (
        <Panel key={i.sale_id}>
          <Text style={styles.section}>{i.name}</Text>
          <Text style={styles.muted}>
            {i.order_number} · {i.inventory_code} · {label(i.order_status)}
          </Text>
          <View style={styles.spread}>
            <Text style={styles.muted}>Your proceeds</Text>
            <Text style={styles.text}>
              {money(i.owner_proceeds_minor, data.summary.currency)}
            </Text>
          </View>
          {!i.financials_complete && (
            <Text style={styles.small}>
              Awaiting final fees and reconciliation
            </Text>
          )}
        </Panel>
      ))}
      {data?.sales.items.length === 0 && (
        <Empty
          title="No sales yet"
          detail="Your sales and proceeds will appear here."
        />
      )}
      <View style={styles.row}>
        <View style={{ flex: 1 }}>
          <Button
            title="Previous sales"
            secondary
            disabled={!offset || loading}
            onPress={() => setOffset(Math.max(0, offset - 20))}
          />
        </View>
        <View style={{ flex: 1 }}>
          <Button
            title="Next sales"
            secondary
            disabled={
              !data ||
              offset + data.sales.items.length >= data.sales.total ||
              loading
            }
            onPress={() => setOffset(offset + 20)}
          />
        </View>
      </View>
      <Text style={styles.section}>Payout history</Text>
      {data?.payouts.items.map((p) => (
        <Panel key={p.payout_code}>
          <View style={styles.spread}>
            <Text style={styles.text}>{p.payout_code}</Text>
            <Text style={styles.text}>{money(p.amount_minor, p.currency)}</Text>
          </View>
          <Text style={{ ...styles.small, color: C.accent }}>
            {label(p.status)}
          </Text>
        </Panel>
      ))}
      {data?.payouts.items.length === 0 && (
        <Text style={styles.muted}>No payouts recorded.</Text>
      )}
      <Button
        title="Manage payouts in Seller Hub"
        secondary
        disabled={demo}
        icon="open-outline"
        onPress={() =>
          void Linking.openURL(DEFAULT_BASE + "/owner").catch((e) =>
            setLinkError(errorMessage(e)),
          )
        }
      />
      <Text style={styles.small}>
        Payout requests and banking details open securely in Seller Hub. Your
        browser may ask you to sign in.
      </Text>
    </Page>
  );
}
