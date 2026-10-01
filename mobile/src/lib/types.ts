export type Role = "OWNER" | "PLATFORM_ADMIN";
export type Access = {
  user_id: string;
  owner_id: string;
  access_role: Role;
  display_name: string;
  portal: "OWNER_PORTAL" | "FOUNDER_HQ";
};
export type Session = {
  access_token: string;
  refresh_token: string;
  expires_at: number;
  user: { id: string };
};
export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};
export type Card = {
  id?: string;
  name: string;
  game?: string;
  set_name?: string;
  card_number?: string;
  variant?: string;
  language?: string;
  product_type?: string;
  image_url?: string | null;
  market_value_minor?: number | null;
  recommended_retail_minor?: number | null;
  source_kind?: string;
  provider?: string;
  provider_id?: string;
  system_code?: string;
  requires_materialization?: boolean;
};
export type Inventory = Card & {
  inventory_code: string;
  status: string;
  condition?: string | null;
  seal_status?: string | null;
  grading_company?: string | null;
  grade?: string | null;
  certificate_number?: string | null;
  store_price_minor?: number | null;
  acquisition_cost_minor?: number | null;
  card_image_direct_url?: string | null;
  location?: string | null;
  storage_location_label?: string | null;
  version?: number;
  notes?: string;
  identity_confirmed?: boolean;
};
export type Candidate = {
  id: string;
  catalogue_id: string | null;
  hard_rejected: boolean;
  source_kind: string;
  score: number;
  candidate_snapshot: Card;
  rejection_reasons?: string[];
};
export type Recognition = {
  run: {
    id: string;
    status: string;
    top_catalogue_id: string | null;
    decision_reasons?: string[];
    error_detail?: string;
  };
  candidates: Candidate[];
  materialized_catalogue_id?: string;
};
export type Selection = {
  card: Card;
  catalogueId: string;
  outcome: "CONFIRMED_TOP" | "CORRECTED_TO_CANDIDATE" | "CORRECTED_BY_SEARCH";
};
export type IntakeResult = {
  inventory?: { inventory_code?: string };
  inventory_code?: string;
  replayed?: boolean;
};
export type PendingIntake = {
  key: string;
  userId: string;
  ownerId: string;
  role: Role;
  path: string;
  payload: Record<string, unknown>;
  title: string;
};
export type ActionItem = {
  id: string;
  title: string;
  detail: string;
  recommended_action: string;
  severity: string;
  category: string;
  entity_id?: string;
  entity_type: string;
};
export type Finance = {
  available_to_withdraw_minor: number;
  pending_minor: number;
  paid_out_minor: number;
  lifetime_owner_proceeds_minor: number;
  financials_complete: boolean;
  currency: string;
};
export type Sale = {
  sale_id: string;
  name: string;
  inventory_code: string;
  order_number: string;
  order_status: string;
  net_sale_minor: number;
  owner_proceeds_minor: number;
  financials_complete: boolean;
};
export type Payout = {
  payout_code: string;
  amount_minor: number;
  currency: string;
  status: string;
};
export const money = (value: number | null | undefined, currency = "GBP") =>
  value == null
    ? "Not valued"
    : new Intl.NumberFormat("en-GB", { style: "currency", currency }).format(
        value / 100,
      );
export const label = (value?: string | null) =>
  (value || "Unknown")
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
export function minorUnits(text: string): number | null {
  if (!text.trim()) return null;
  if (!/^\d+(\.\d{1,2})?$/.test(text.trim()))
    throw new Error("Enter a positive amount with up to two decimal places.");
  const [whole, cents = ""] = text.trim().split(".");
  const value = Number(whole) * 100 + Number(cents.padEnd(2, "0"));
  if (!Number.isSafeInteger(value))
    throw new Error("That amount is too large.");
  return value;
}
