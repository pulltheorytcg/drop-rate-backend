"use strict";

function lotMoneyInput(id, allowBlank = false) {
  const value = byId(id).value.trim();
  if (!value && allowBlank) return 0;
  return inputToMinor(value, false);
}

function landedLotTotal() {
  return lotMoneyInput("lot-price") + lotMoneyInput("lot-fees", true) + lotMoneyInput("lot-shipping", true);
}

function selectedLotRows() {
  return [...byId("lot-allocation-list").querySelectorAll(".allocation-row")];
}

function renderPurchaseLots(data) {
  const container = byId("purchase-lots-list");
  container.replaceChildren();
  if (!data.items.length) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "No purchase lots yet. Create one when you review a binder, collection or set purchase.";
    container.append(empty);
    return;
  }

  data.items.forEach((lot) => {
    const row = document.createElement("div");
    row.className = "allocation-row";

    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = lot.description;
    const meta = document.createElement("small");
    meta.textContent = [lot.lot_code, lot.source, lot.purchase_date, `${lot.item_count} card${lot.item_count === 1 ? "" : "s"}`].filter(Boolean).join(" · ");
    details.append(title, meta);

    const totals = document.createElement("div");
    totals.className = "card-name";
    const total = document.createElement("strong");
    total.textContent = `${money(lot.allocated_cost_minor, lot.currency)} / ${money(lot.total_cost_minor, lot.currency)}`;
    const remaining = document.createElement("small");
    remaining.textContent = lot.remaining_cost_minor === 0 ? "Fully allocated" : `${money(lot.remaining_cost_minor, lot.currency)} remaining`;
    totals.append(total, remaining);

    row.append(details, totals);
    container.append(row);
  });
}

async function loadPurchaseLots() {
  if (!state.session?.access_token || byId("dashboard-view").classList.contains("hidden")) return;
  showMessage("lots-message", "Loading purchase lots…");
  try {
    renderPurchaseLots(await apiRequest("/api/v1/purchase-lots"));
    showMessage("lots-message");
  } catch (error) {
    showMessage("lots-message", error.message, "error");
  }
}

function updateLotAllocationRemaining() {
  const summary = byId("lot-remaining");
  const rows = selectedLotRows();
  if (!rows.length) {
    summary.textContent = "No cards selected — the lot will be saved for later allocation.";
    summary.className = "";
    return;
  }
  try {
    const total = landedLotTotal();
    let allocated = 0;
    let blanks = 0;
    rows.forEach((row) => {
      const input = row.querySelector("input");
      if (!input.value.trim()) { blanks += 1; return; }
      allocated += inputToMinor(input.value, false);
    });
    const remaining = total - allocated;
    if (blanks) {
      summary.textContent = `${blanks} card${blanks === 1 ? "" : "s"} still need an allocated cost.`;
      summary.className = "error";
    } else if (remaining < 0) {
      summary.textContent = `${money(Math.abs(remaining))} over the landed cost`;
      summary.className = "error";
    } else if (remaining === 0) {
      summary.textContent = "Fully allocated";
      summary.className = "ok";
    } else {
      summary.textContent = `${money(remaining)} remaining in this purchase lot`;
      summary.className = "";
    }
  } catch (_error) {
    summary.textContent = "Enter a valid purchase price to review the allocation.";
    summary.className = "error";
  }
}

function renderSelectedLotCards() {
  const items = [...state.selected.values()];
  byId("lot-item-count").textContent = `${items.length} selected card${items.length === 1 ? "" : "s"}`;
  const list = byId("lot-allocation-list");
  list.replaceChildren();

  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "allocation-row";
    row.dataset.id = item.id;

    const details = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = item.name;
    const meta = document.createElement("small");
    meta.textContent = [item.set_name, item.inventory_code, item.purchase_lot_code ? `Already: ${item.purchase_lot_code}` : null].filter(Boolean).join(" · ");
    details.append(title, meta);

    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.step = "0.01";
    input.placeholder = "Unknown";
    input.value = minorToInput(item.acquisition_cost_minor);
    input.setAttribute("aria-label", `Allocated cost for ${item.name}`);
    input.addEventListener("input", updateLotAllocationRemaining);

    row.append(details, input);
    list.append(row);
  });
  updateLotAllocationRemaining();
}

function resetPurchaseLotForm() {
  byId("purchase-lot-form").reset();
  byId("lot-method").value = "MANUAL";
  showMessage("lot-message");
  renderSelectedLotCards();
}

function splitLotEqually() {
  try {
    const rows = selectedLotRows();
    if (!rows.length) throw new Error("Select cards in inventory before splitting the lot cost.");
    const total = landedLotTotal();
    const base = Math.floor(total / rows.length);
    let remainder = total - (base * rows.length);
    rows.forEach((row) => {
      const amount = base + (remainder > 0 ? 1 : 0);
      if (remainder > 0) remainder -= 1;
      row.querySelector("input").value = (amount / 100).toFixed(2);
    });
    byId("lot-method").value = "EQUAL";
    updateLotAllocationRemaining();
  } catch (error) {
    showMessage("lot-message", error.message, "error");
  }
}

async function savePurchaseLot(event) {
  event.preventDefault();
  const form = event.currentTarget;
  setBusy(form, true);
  showMessage("lot-message");
  try {
    const payload = {
      description: byId("lot-description").value.trim(),
      source: emptyToNull(byId("lot-source").value),
      purchase_date: byId("lot-date").value || null,
      purchase_price_minor: lotMoneyInput("lot-price"),
      fees_minor: lotMoneyInput("lot-fees", true),
      shipping_minor: lotMoneyInput("lot-shipping", true),
      currency: "GBP",
      allocation_method: byId("lot-method").value,
      notes: byId("lot-notes").value.trim(),
    };

    const rows = selectedLotRows();
    const allocationItems = rows.map((row) => {
      const selected = state.selected.get(row.dataset.id);
      const input = row.querySelector("input");
      if (!input.value.trim()) throw new Error(`Enter an allocated cost for ${selected.name}, or remove it from the selection.`);
      if (selected.purchase_lot_id) throw new Error(`${selected.name} already belongs to purchase lot ${selected.purchase_lot_code || selected.purchase_lot_id}.`);
      return {
        inventory_id: selected.id,
        version: selected.version,
        acquisition_cost_minor: inputToMinor(input.value, false),
      };
    });

    const allocated = allocationItems.reduce((sum, item) => sum + item.acquisition_cost_minor, 0);
    const total = payload.purchase_price_minor + payload.fees_minor + payload.shipping_minor;
    if (allocated > total) throw new Error("Allocated card costs cannot exceed the landed purchase cost.");

    const lot = await apiRequest("/api/v1/purchase-lots", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    if (allocationItems.length) {
      await apiRequest(`/api/v1/purchase-lots/${lot.id}/allocate`, {
        method: "POST",
        body: JSON.stringify({ version: lot.version, items: allocationItems }),
      });
    }

    state.selected.clear();
    byId("purchase-lot-dialog").close();
    await Promise.all([reloadDashboard(), loadPurchaseLots()]);
    showMessage("lots-message", allocationItems.length
      ? `Purchase lot ${lot.lot_code} created and ${allocationItems.length} cards allocated.`
      : `Purchase lot ${lot.lot_code} created.`, "success");
  } catch (error) {
    showMessage("lot-message", error.message, "error");
  } finally {
    setBusy(form, false);
  }
}

byId("new-lot-button").addEventListener("click", () => {
  resetPurchaseLotForm();
  byId("purchase-lot-dialog").showModal();
});
byId("refresh-lots-button").addEventListener("click", loadPurchaseLots);
byId("lot-equal-split").addEventListener("click", splitLotEqually);
byId("purchase-lot-form").addEventListener("submit", savePurchaseLot);
["lot-price", "lot-fees", "lot-shipping"].forEach((id) => byId(id).addEventListener("input", updateLotAllocationRemaining));

// Preserve the accounting distinction between an unknown cost and a genuine £0 cost.
// The original bulk dialog pre-dates purchase lots and displayed unknown values as 0.00.
byId("bulk-cost-button").addEventListener("click", () => {
  allocationRows().forEach((row) => {
    const selected = state.selected.get(row.dataset.id);
    if (selected?.acquisition_cost_minor === null || selected?.acquisition_cost_minor === undefined) {
      row.querySelector("input").value = "";
      row.querySelector("input").placeholder = "Unknown";
    }
  });
  updateAllocationRemaining();
});

const dashboardObserver = new MutationObserver(() => {
  if (!byId("dashboard-view").classList.contains("hidden")) loadPurchaseLots();
});
dashboardObserver.observe(byId("dashboard-view"), { attributes: true, attributeFilter: ["class"] });
