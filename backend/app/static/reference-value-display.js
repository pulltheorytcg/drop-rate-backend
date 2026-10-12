"use strict";
window.DropRateReferenceValue = Object.freeze({
  text(item, money) {
    const ref = item?.reference_value;
    if (!ref) return item?.market_value_minor == null ? "Value unavailable" : money(item.market_value_minor);
    if (["AVAILABLE", "REFERENCE_ESTIMATE"].includes(ref.status) && Number.isInteger(ref.market_value_minor)) {
      return money(ref.market_value_minor) + (ref.status === "REFERENCE_ESTIMATE" ? " · Guide estimate" : "");
    }
    return ({STALE: "Stale evidence — value unavailable", NEEDS_DETAILS: "Confirm details for value"})[ref.status] || "No exact market evidence";
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
    const ref = item?.reference_value;
    if (!ref) return "";
    const time = ref.checked_at ? new Date(ref.checked_at) : null;
    return [ref.basis, ref.reason, time && !Number.isNaN(time.getTime()) ? "Evidence checked " + time.toLocaleDateString("en-GB") : null].filter(Boolean).join(" · ");
  }
});
