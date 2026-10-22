"use strict";
window.DropRateReferenceValue = Object.freeze({
  displayReference(item) {
    const ref = item?.reference_value;
    return ["AVAILABLE", "REFERENCE_ESTIMATE"].includes(ref?.status) ? ref : item?.catalogue_reference || ref;
  },
  text(item, money) {
    const ref = this.displayReference(item);
    if (!ref) return item?.market_value_minor == null ? "Value unavailable" : money(item.market_value_minor);
    if (["AVAILABLE", "REFERENCE_ESTIMATE"].includes(ref.status) && Number.isInteger(ref.market_value_minor)) {
      return money(ref.market_value_minor) + (ref.status === "REFERENCE_ESTIMATE" ? " · Guide estimate" : "");
    }
    if (["CATALOGUE_GUIDE", "CONDITION_REFERENCE"].includes(ref.status) && Number.isInteger(ref.market_value_minor)) {
      const high = ref.market_value_high_minor;
      return money(ref.market_value_minor) + (Number.isInteger(high) && high > ref.market_value_minor ? "–" + money(high) : "")
        + " · " + ref.label;
    }
    if (Number.isInteger(ref.last_known_minor) && ref.checked_at) {
      const date = new Date(ref.checked_at);
      if (!Number.isNaN(date.getTime())) return money(ref.last_known_minor)
        + (Number.isInteger(ref.last_known_high_minor) && ref.last_known_high_minor > ref.last_known_minor ? "–" + money(ref.last_known_high_minor) : "")
        + " · Last known " + date.toLocaleDateString("en-GB");
    }
    return ({STALE: "Stale evidence — value unavailable", NEEDS_DETAILS: "Confirm details for value"})[ref.status] || "No exact market evidence";
  },
  isHistorical(item) {
    const ref = this.displayReference(item);
    return ref != null && !["AVAILABLE", "REFERENCE_ESTIMATE", "CATALOGUE_GUIDE", "CONDITION_REFERENCE"].includes(ref.status)
      && Number.isInteger(ref.last_known_minor) && Boolean(ref.checked_at);
  },
  compactText(item, money) {
    // The exact observation date remains visible in details, not the mobile
    // two-column grid. A visual historical label is added by the tile itself.
    if (!this.isHistorical(item)) return this.text(item, money);
    const ref = this.displayReference(item);
    return money(ref.last_known_minor)
      + (Number.isInteger(ref.last_known_high_minor) && ref.last_known_high_minor > ref.last_known_minor ? "–" + money(ref.last_known_high_minor) : "");
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
    return [ref.basis, ref.reason, time && !Number.isNaN(time.getTime()) ? "Evidence checked " + time.toLocaleDateString("en-GB") : null].filter(Boolean).join(" · ");
  }
});
