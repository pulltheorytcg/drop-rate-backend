import { Api, type Vault } from "./api";
import type { Role, Inventory, Access, Recognition } from "./types";
export function createDemo(role: Role) {
  const values = new Map<string, string>();
  const storage: Vault = {
    get: async (k) => values.get(k) ?? null,
    set: async (k, v) => {
      values.set(k, v);
    },
    remove: async (k) => {
      values.delete(k);
    },
  };
  const access: Access = {
    user_id: "demo-user",
    owner_id: "demo-owner",
    access_role: role,
    display_name: "Alex Morgan",
    portal: role === "OWNER" ? "OWNER_PORTAL" : "FOUNDER_HQ",
  };
  const items: Inventory[] = [
    {
      id: "demo-1",
      inventory_code: "PT-000184",
      name: "Charizard ex",
      game: "Pokémon",
      set_name: "Scarlet & Violet — 151",
      card_number: "199/165",
      variant: "Special Illustration Rare",
      language: "English",
      condition: "NM",
      status: "APPROVED",
      market_value_minor: 16450,
      store_price_minor: 17500,
      product_type: "CARD",
      version: 1,
      acquisition_cost_minor: 11000,
      identity_confirmed: true,
      location: "Vault A · 03",
    },
    {
      id: "demo-2",
      inventory_code: "PT-000185",
      name: "Monkey D. Luffy",
      game: "One Piece",
      set_name: "Romance Dawn",
      card_number: "OP01-003",
      variant: "Parallel",
      language: "Japanese",
      condition: "NM",
      status: "INSPECTION",
      market_value_minor: 4200,
      store_price_minor: null,
      product_type: "CARD",
      version: 1,
    },
    {
      id: "demo-3",
      inventory_code: "PT-000186",
      name: "Pikachu",
      game: "Pokémon",
      set_name: "Crown Zenith",
      card_number: "160/159",
      language: "English",
      condition: "NM",
      status: "APPROVED",
      market_value_minor: 2350,
      store_price_minor: 2600,
      product_type: "CARD",
      version: 1,
    },
    {
      id: "demo-4",
      inventory_code: "PT-000187",
      name: "Son Goku",
      game: "Dragon Ball",
      set_name: "Fusion World",
      card_number: "FB01-001",
      language: "English",
      status: "DRAFT",
      condition: "NM",
      market_value_minor: null,
      product_type: "CARD",
      version: 1,
    },
  ];
  const result: Recognition = {
    run: { id: "demo-run", status: "NEEDS_REVIEW", top_catalogue_id: "demo-1" },
    candidates: [
      {
        id: "demo-candidate",
        catalogue_id: "demo-1",
        hard_rejected: false,
        source_kind: "CATALOGUE",
        score: 0.89,
        candidate_snapshot: items[0],
      },
      {
        id: "demo-unmapped",
        catalogue_id: null,
        hard_rejected: false,
        source_kind: "PROVIDER",
        score: 0.85,
        candidate_snapshot: {
          ...items[1],
          name: "Trafalgar Law",
          set_name: "Awakening of the New Era",
          card_number: "OP05-069",
        },
      },
    ],
  };
  const receipts = new Map<string, unknown>();
  const transport: typeof fetch = async (input, init) => {
    const url = new URL(String(input));
    const path = url.pathname;
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    let data: unknown = {};
    let status = 200;
    if (path.endsWith("/owner-session") || path.endsWith("/token"))
      data = {
        access_token: "demo-only",
        refresh_token: "demo-only",
        expires_at: Date.now() / 1000 + 3600,
        user: { id: access.user_id },
      };
    else if (path.endsWith("/public-config"))
      data = {
        supabase_url: "https://demo.supabase.co",
        publishable_key: "demo",
      };
    else if (path.endsWith("/access/me")) data = { access };
    else if (path.endsWith("/inventory/readiness"))
      data = {
        total: 4,
        approved: 2,
        identity_unconfirmed: 2,
        missing_price: 2,
      };
    else if (path.endsWith("/owner/overview"))
      data = {
        summary: {
          total_inventory_count: 4,
          active_market_value_minor: 23000,
          active_store_value_minor: 20100,
          approved_count: 2,
          draft_count: 1,
        },
      };
    else if (path.endsWith("/inventory")) {
      const filtered = items.filter(
        (i) =>
          (!url.searchParams.get("search") ||
            `${i.name} ${i.inventory_code} ${i.card_number}`
              .toLowerCase()
              .includes(url.searchParams.get("search")!.toLowerCase())) &&
          (!url.searchParams.get("status") ||
            i.status === url.searchParams.get("status")),
      );
      data = { items: filtered, total: filtered.length, offset: 0, limit: 50 };
    } else if (path.endsWith("/action-required"))
      data = {
        total: 2,
        items: [
          {
            id: "action-1",
            title: "Slab photos needed",
            detail:
              "Add clear front and back photographs before this graded card can be published.",
            recommended_action: "Review physical media in Founder HQ.",
            severity: "HIGH",
            category: "MEDIA",
            entity_type: "INVENTORY_ITEM",
          },
          {
            id: "action-2",
            title: "Review card identity",
            detail: "The exact printing needs a second check.",
            recommended_action:
              "Check the set, card number, language and variant.",
            severity: "MEDIUM",
            category: "IDENTITY",
            entity_type: "INVENTORY_ITEM",
          },
        ],
      };
    else if (path.endsWith("/finance/summary"))
      data = {
        currency: "GBP",
        available_to_withdraw_minor: 12850,
        pending_minor: 4200,
        paid_out_minor: 31200,
        lifetime_owner_proceeds_minor: 48250,
        financials_complete: true,
      };
    else if (path.endsWith("/finance/sales"))
      data = {
        total: 1,
        items: [
          {
            sale_id: "sale-1",
            name: "Eevee",
            inventory_code: "PT-000102",
            order_number: "#1042",
            order_status: "PAID",
            net_sale_minor: 3600,
            owner_proceeds_minor: 2980,
            financials_complete: true,
          },
        ],
      };
    else if (path.endsWith("/finance/payouts"))
      data = {
        items: [
          {
            payout_code: "PAY-00012",
            amount_minor: 31200,
            currency: "GBP",
            status: "PAID",
          },
        ],
      };
    else if (path.endsWith("/recognition/resolve")) data = result;
    else if (path.endsWith("/materialize"))
      data = { ...result, materialized_catalogue_id: "demo-2" };
    else if (
      path.endsWith("/catalogue-search") ||
      path.endsWith("/catalogue/search")
    )
      data = { items };
    else if (path.endsWith("/feedback")) data = { recorded: true };
    else if (
      path.endsWith("/recognition-intake") ||
      path.endsWith("/inventory/intake")
    ) {
      const key = new Headers(init?.headers).get("Idempotency-Key")!;
      if (receipts.has(key)) data = receipts.get(key);
      else {
        const code = "PT-DEMO-" + (items.length + 1);
        items.unshift({
          ...items[0],
          id: code,
          inventory_code: code,
          status: "DRAFT",
          identity_confirmed: false,
        });
        data = { inventory: { inventory_code: code } };
        receipts.set(key, data);
      }
    } else if (path.includes("/inventory/") && init?.method === "PATCH") {
      const item = items.find((i) => i.id === path.split("/").pop());
      if (item && item.version === body.version) {
        Object.assign(item, body, { version: (item.version ?? 0) + 1 });
        data = item;
      } else {
        status = 409;
        data = { detail: "Item changed" };
      }
    } else if (path.endsWith("/owner/profile"))
      data = {
        profile: {
          display_name: body.display_name || access.display_name,
          username: body.username || "alexmorgan",
          owner_type: "CONSIGNOR",
        },
        email: "demo@example.invalid",
      };
    else if (!path.endsWith("/logout")) {
      status = 404;
      data = { detail: "This action is not available in the demo." };
    }
    return new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };
  return new Api(storage, "https://demo.pulltheory.invalid", transport);
}
