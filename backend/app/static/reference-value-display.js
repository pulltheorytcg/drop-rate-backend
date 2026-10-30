"use strict";
window.DropRateReferenceValue = Object.freeze({
  displayReference(item) {
    const ref = item?.reference_value;
    return ["AVAILABLE", "REFERENCE_ESTIMATE"].includes(ref?.status) ? ref : item?.catalogue_reference || ref;
  },
  text(item, money) {
    const ref = this.displayReference(item);
    if (!ref) return item?.market_value_minor == null ? "Value unavailable" : "Value: " + money(item.market_value_minor);
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
    const time = ref.checked_at ? new Date(ref.checked_at) : null;
    const history = this.isHistorical(item) && time && !Number.isNaN(time.getTime()) ? "Last known " + time.toLocaleDateString("en-GB") : null;
    return [ref.label, history, ref.basis, ref.reason, time && !Number.isNaN(time.getTime()) ? "Evidence checked " + time.toLocaleDateString("en-GB") : null].filter(Boolean).join(" · ");
  }
});
