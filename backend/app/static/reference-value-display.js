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
    const candidate = item?.reference_value;
    const ref = candidate?.method === "DROP_RATE_UK_EU_MARKET_V1" && !this.ukEuEstimate(candidate) ? null : candidate;
    if (["AVAILABLE", "REFERENCE_ESTIMATE", "CONDITION_REFERENCE"].includes(ref?.status)) return ref;
    const catalogue = item?.catalogue_reference;
    if (catalogue?.method === "DROP_RATE_UK_EU_MARKET_V1" && !this.ukEuEstimate(catalogue)) return ref;
    return catalogue || ref;
  },
  text(item, money) {
    const ref = this.displayReference(item);
    if (!ref) return item?.market_value_minor == null ? "Value unavailable" : "Value: " + money(item.market_value_minor);
    if (this.ukEuEstimate(ref)) return "Drop Rate UK/EU estimate: " + money(ref.estimate_minor ?? ref.market_value_minor);
    if (["AVAILABLE", "REFERENCE_ESTIMATE"].includes(ref.status) && Number.isInteger(ref.market_value_minor)) {
      return "Value: " + money(ref.market_value_minor);
    }
    if (["CATALOGUE_GUIDE", "CONDITION_REFERENCE"].includes(ref.status) && Number.isInteger(ref.market_value_minor)) {
      return "Value: " + money(ref.market_value_minor);
    }
    if (Number.isInteger(ref.last_known_minor) && ref.checked_at) {
      const date = new Date(ref.checked_at);
      if (!Number.isNaN(date.getTime())) return "Value: " + money(ref.last_known_minor);
    }
    return ({STALE: "Stale evidence — value unavailable", NEEDS_DETAILS: "Confirm details for value"})[ref.status] || "No exact market evidence";
  },
  isHistorical(item) {
    const ref = this.displayReference(item);
    return ref != null && !["AVAILABLE", "REFERENCE_ESTIMATE", "CATALOGUE_GUIDE", "CONDITION_REFERENCE"].includes(ref.status)
      && Number.isInteger(ref.last_known_minor) && Boolean(ref.checked_at);
  },
  label(item) {
    const ref = this.displayReference(item);
    if (this.ukEuEstimate(ref)) return "Drop Rate UK/EU estimate";
    if (ref?.method === "DROP_RATE_COMPUTED_MARKET_V1") return "Drop Rate estimate";
    if (["REFERENCE_ESTIMATE", "CATALOGUE_GUIDE", "CONDITION_REFERENCE"].includes(ref?.status)) return "Guide estimate";
    return "Market value";
  },
  compactText(item, money) {
    // The exact observation date remains visible in details, not the mobile
    // two-column grid. A visual historical label is added by the tile itself.
    if (!this.isHistorical(item)) return this.text(item, money);
    const ref = this.displayReference(item);
    return "Value: " + money(ref.last_known_minor);
  },
  recommendedMinor(item) {
    const ref = item?.reference_value;
    if (ref?.method === "DROP_RATE_UK_EU_MARKET_V1") return null;
    return ref && ["AVAILABLE", "REFERENCE_ESTIMATE"].includes(ref.status)
      && Number.isInteger(ref.recommended_retail_minor) && ref.recommended_retail_minor >= 100
      ? ref.recommended_retail_minor : null;
  },
  recommendationText(item, money) {
    const amount = this.recommendedMinor(item);
    return amount == null ? "Recommendation unavailable"
      : money(amount) + (item.reference_value.status === "REFERENCE_ESTIMATE" ? " · Guide estimate" : "");
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

