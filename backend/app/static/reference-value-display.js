"use strict";
// Pricing rules (owner decisions, 27 Nov 2026) — see docs/PRICING_RULES.md:
// 1. Market Value = exact UK sold evidence; otherwise a clearly labelled
//    Cardmarket EU guide estimate (raw NM/unknown-condition cards only; the
//    backend enforces eligibility). Internal models and US prices never.
// 4. Expired values are never current and never totalled, but show as
//    "Last known £X · date".
window.DropRateReferenceValue = Object.freeze({
  // Estimate methods that may display as a labelled, totalled value: the UK
  // eBay asking average checked against Cardmarket (owner rule, 28 Nov 2026)
  // and the Cardmarket EU guide.
  euGuideMethods: Object.freeze(["UK_ASKING_AVERAGE_V1", "CATALOGUE_CARDMARKET_V1", "CARDMARKET_CATALOGUE_GUIDE"]),
  isAskingAverage(ref) {
    return Boolean(ref) && ref.method === "UK_ASKING_AVERAGE_V1";
  },
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
  isEuGuide(source) {
    return Boolean(source) && ["REFERENCE_ESTIMATE", "CATALOGUE_GUIDE"].includes(source.status)
      && this.euGuideMethods.includes(source.method);
  },
  displayReference(item) {
    const source = item?.reference_value || item?.catalogue_reference;
    if (!source) return { status: "UNAVAILABLE", market_value_minor: null };
    const guideMethods = new Set([
      "CATALOGUE_CARDMARKET_V1", "CARDMARKET_CATALOGUE_GUIDE", "DROP_RATE_UK_EU_MARKET_V1",
      "DROP_RATE_COMPUTED_MARKET_V1"
    ]);
    // Exact UK sold evidence is the current Market Value.
    if (source.status === "AVAILABLE" && !guideMethods.has(source.method)) return source;
    // A Cardmarket EU guide is a labelled estimate, never a retail suggestion.
    if (this.isEuGuide(source)) return { ...source, last_known_minor: null,
      recommended_retail_minor: null, estimate_minor: null };
    // Expired evidence keeps only its dated last-known amount.
    if (source.status === "STALE") return { ...source, market_value_minor: null,
      recommended_retail_minor: null, estimate_minor: null };
    return { ...source, market_value_minor: null, last_known_minor: null,
      recommended_retail_minor: null, estimate_minor: null };
  },
  estimateText(ref, money) {
    if (this.isAskingAverage(ref)) {
      const sellers = Number.isSafeInteger(ref.seller_count) && ref.seller_count >= 3 ? " · " + ref.seller_count + " sellers" : "";
      return "UK asking average: " + money(ref.market_value_minor) + sellers;
    }
    const low = ref.market_value_minor, high = ref.market_value_high_minor;
    const range = Number.isSafeInteger(high) && high > low ? money(low) + "–" + money(high) : money(low);
    return "Estimate: " + range + " · Cardmarket EU guide";
  },
  lastKnownText(ref, money) {
    const amount = ref.last_known_minor, time = ref.checked_at ? new Date(ref.checked_at) : null;
    if (!Number.isSafeInteger(amount) || amount <= 0) return null;
    const date = time && !Number.isNaN(time.getTime()) ? " · " + time.toLocaleDateString("en-GB") : "";
    return "Last known " + money(amount) + date;
  },
  text(item, money) {
    const ref = this.displayReference(item);
    const amount = ref.market_value_minor;
    if (ref.status === "AVAILABLE" && Number.isSafeInteger(amount) && amount > 0) return "Value: " + money(amount);
    if (this.isEuGuide(ref) && Number.isSafeInteger(amount) && amount > 0) return this.estimateText(ref, money);
    if (ref.status === "NEEDS_DETAILS") return "Confirm details for value";
    if (ref.status === "STALE") return this.lastKnownText(ref, money) || "Stale evidence — value unavailable";
    return "Value unavailable";
  },
  isHistorical(item) {
    // A dated last-known amount is history, never the current field.
    const ref = item?.reference_value || item?.catalogue_reference;
    return ref?.status === "STALE" && Number.isSafeInteger(ref.last_known_minor) && ref.last_known_minor > 0;
  },
  label() {
    return "Market value";
  },
  marketMinor(item) {
    // Totals: UK sold values plus snapshot-based Cardmarket estimates (shown
    // separately as "of which estimates"). Catalogue-wide guide ranges and
    // expired values are display-only.
    const ref = this.displayReference(item);
    const amount = ref.market_value_minor;
    const counted = ref.status === "AVAILABLE"
      || (ref.status === "REFERENCE_ESTIMATE" && this.isEuGuide(ref));
    return counted && Number.isSafeInteger(amount) && amount > 0 ? amount : null;
  },
  compactText(item, money) {
    // Small tiles and list cells show only the last-known amount; callers add
    // a "Historical value" tag, and the date stays in the item details.
    const ref = this.displayReference(item);
    if (ref.status === "STALE" && Number.isSafeInteger(ref.last_known_minor) && ref.last_known_minor > 0)
      return money(ref.last_known_minor);
    return this.text(item, money);
  },
  recommendedMinor() {
    // A retail or provider guide is not a retail recommendation.
    return null;
  },
  recommendationText() {
    return "Recommendation unavailable";
  },
  description(item) {
    const ref = this.displayReference(item);
    if (!ref) return "";
    const time = ref.checked_at ? new Date(ref.checked_at) : null;
    const checked = time && !Number.isNaN(time.getTime()) ? "Evidence checked " + time.toLocaleDateString("en-GB") : null;
    if (this.isEuGuide(ref) && Number.isSafeInteger(ref.market_value_minor))
      return [ref.label || "Estimate · Cardmarket EU guide", ref.basis, ref.reason,
        this.isAskingAverage(ref) && checked ? checked.replace("Evidence checked", "Listings checked") : checked
      ].filter(Boolean).join(" · ");
    if (ref.status === "STALE" && Number.isSafeInteger(ref.last_known_minor))
      return [ref.label, ref.basis, "No current value: evidence has expired", checked].filter(Boolean).join(" · ");
    if (ref.status !== "AVAILABLE") return "";
    if (this.ukEuEstimate(ref)) return [ref.reason || "Provisional estimate from eBay UK asking prices and Cardmarket guides.",
      "Item price only; postage excluded", "Evidence checked " + new Date(ref.observed_at).toLocaleDateString("en-GB")].join(" · ");
    return [ref.label, ref.basis, ref.reason, checked].filter(Boolean).join(" · ");
  }
});
