"use strict";

// Display groups only. Every action still targets an original physical copy.
window.DropRateInventoryGroups = (() => {
  const active = new Set(["DRAFT", "INSPECTION", "APPROVED", "RESERVED"]);
  function key(item) {
    const raw = ["CARD", "SEALED", "COLLECTION"].includes(item.product_type)
      && item.catalogue_id && !item.has_certificate && ![item.grading_company, item.grade, item.certificate_number]
        .some(value => String(value ?? "").trim());
    return JSON.stringify(raw ? [item.owner_id || "", item.catalogue_id, item.product_type,
      (String(item.language || "").trim() || String(item.catalogue_language || "").trim()), item.condition || "",
      item.seal_status || "", item.variant || "", active.has(item.status) ? "ACTIVE" : item.status]
      : [item.owner_id || "", item.id]);
  }
  function priceRank(item) {
    const ref = window.DropRateReferenceValue?.displayReference(item);
    if (Number.isInteger(ref?.market_value_minor)) return ref.status === "AVAILABLE" ? 4 : 3;
    if (!ref && Number.isInteger(item.market_value_minor)) return 4;
    return Number.isInteger(ref?.last_known_minor) ? 1 : 0;
  }
  function group(items) {
    const groups = new Map();
    for (const original of items) {
      const signature = key(original);
      if (!groups.has(signature)) groups.set(signature, []);
      groups.get(signature).push(original);
    }
    return [...groups.values()].map(copies => {
      const first = copies[0], item = {...first};
      item.group_members = copies;
      item.group_member_ids = copies.map(copy => copy.id);
      item.grouped_quantity = copies.length;
      item.group_valued_count = copies.filter(copy => Number.isInteger(copy.market_value_minor)).length;
      item.group_unvalued_code = copies.find(copy => copy.can_refresh_market && copy.market_value_minor == null)?.inventory_code;
      item.can_refresh_market = copies.some(copy => copy.can_refresh_market);
      item.group_status_label = [...new Set(copies.map(copy => copy.status))].length > 1 ? "Mixed status" : first.status;
      item.group_status_description = [...new Set(copies.map(copy => copy.status))]
        .map(status => `${copies.filter(copy => copy.status === status).length} ${status.toLowerCase()}`).join(" · ");
      // Prefer an evidenced display over an empty representative. This changes
      // neither the original copy nor its eligibility for financial totals.
      const priced = copies.reduce((best, copy) => priceRank(copy) > priceRank(best) ? copy : best, first);
      for (const field of ["reference_value", "catalogue_reference", "market_value_minor", "pricing_method", "pricing_updated_at"])
        item[field] = priced[field];
      return item;
    });
  }
  function moneyRange(item, field, money, fallback = "—") {
    const copies = item.group_members || [item];
    const values = [...new Set(copies.map(copy => copy[field]).filter(Number.isInteger))].sort((a,b) => a-b);
    if (!values.length) return fallback;
    const amount = money(values[0]) + (values.length > 1 ? "–" + money(values.at(-1)) : "");
    return amount + (copies.some(copy => !Number.isInteger(copy[field])) ? " · some unset" : "");
  }
  return Object.freeze({group, key, moneyRange});
})();
