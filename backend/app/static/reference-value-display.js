"use strict";
window.DropRateReferenceValue = Object.freeze({
  ukEuEstimate(ref) {
    if (!ref || !["UK_EU_MARKET_ESTIMATE", "CATALOGUE_GUIDE"].includes(ref.status)
      || ref.method !== "DROP_RATE_UK_EU_MARKET_V1" || ref.currency !== "GBP"
      || ref.shipping_basis !== "ITEM_ONLY" || ref.physical_valuation_eligible !== false) return null;
    const amount = ref.estimate_minor ?? ref.market_value_minor;
    if (!Number.isSafeInteger(amount) || amount <= 0
      || !Number.isSafeInteger(ref.estimate_low_minor) || ref.estimate_low_minor <= 0 || ref.estimate_low_minor > amount
      || !Number.isSafeInteger(ref.estimate_high_minor) || ref.estimate_high_minor < amount
      || typeof ref.confidence !== "number" || !Number.isFinite(ref.confidence) || ref.confidence < 0 || ref.confidence > 0.60
      || typeof ref.observed_at !== "string" || typeof ref.expires_at !== "string") return null;
    const observed = Date.parse(ref.observed_at), expires = Date.parse(ref.expires_at), now = Date.now(), maxAge = 7 * 86400000;
    return Number.isFinite(observed) && Number.isFinite(expires) && observed <= now && observed >= now - maxAge
      && expires > now && expires <= observed + maxAge ? ref : null;
  },
  displayReference(item) {
    const source = item?.reference_value || item?.catalogue_reference;
    if (!source) return { status: "UNAVAILABLE", market_value_minor: null };
    // Only the backend's exact sold-evidence AVAILABLE outcome can supply a
    // *current* physical Market Value. Guide, retail, historical and a
    // condition-reference for an uninspected copy MUST stay non-monetary.
    const guideMethods = new Set([
      "CATALOGUE_CARDMARKET_V1", "DROP_RATE_UK_EU_MARKET_V1",
      "DROP_RATE_COMPUTED_MARKET_V1"
    ]);
    if (source.status === "AVAILABLE" && !guideMethods.has(source.method)) return source;
    return { ...source, market_value_minor: null, last_known_minor: null,
      recommended_retail_minor: null, estimate_minor: null };
  },
  text(item, money) {
    const ref = this.displayReference(item);
    const amount = ref.status === "AVAILABLE" ? ref.market_value_minor : null;
    if (Number.isSafeInteger(amount) && amount > 0) return "Value: " + money(amount);
    if (ref.status === "NEEDS_DETAILS") return "Confirm details for value";
    if (ref.status === "STALE") return "Stale evidence — value unavailable";
    return "Value unavailable";
  },
  isHistorical() {
    // Historical values belong in a dated history view, never the current
    // Market Value field or owner portfolio totals.
    return false;
  },
  label() {
    return "Market value";
  },
  marketMinor(item) {
    const ref = this.displayReference(item);
    const amount = ref.status === "AVAILABLE" ? ref.market_value_minor : null;
    return Number.isSafeInteger(amount) && amount > 0 ? amount : null;
  },
  compactText(item, money) {
    return this.text(item, money);
  },
  recommendedMinor() {
    // A retail or provider guide is not Market Value.
    return null;
  },
  recommendationText() {
    return "Recommendation unavailable";
  },
  description(item) {
    const ref = this.displayReference(item);
    if (!ref) return "";
    if (this.ukEuEstimate(ref)) return [ref.reason || "Provisional estimate from eBay UK asking prices and Cardmarket guides.",
      "Item price only; postage excluded", "Evidence checked " + new Date(ref.observed_at).toLocaleDateString("en-GB")].join(" · ");
    const time = ref.checked_at ? new Date(ref.checked_at) : null;
    const history = this.isHistorical(item) && time && !Number.isNaN(time.getTime()) ? "Last known " + time.toLocaleDateString("en-GB") : null;
    return [ref.label, history, ref.basis, ref.reason, time && !Number.isNaN(time.getTime()) ? "Evidence checked " + time.toLocaleDateString("en-GB") : null].filter(Boolean).join(" · ");
  }
});

