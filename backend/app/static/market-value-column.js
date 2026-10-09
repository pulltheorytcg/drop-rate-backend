"use strict";

(function attachMarketValueColumn() {
  function formatGBP(value) {
    if (value === null || value === undefined) return "Value pending";
    return new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" }).format(value / 100);
  }

  function ensureHeader() {
    const headerRow = document.querySelector("#inventory-body")?.closest("table")?.querySelector("thead tr");
    if (!headerRow || headerRow.querySelector("th[data-market-value-column]")) return;

    const storePriceHeader = [...headerRow.querySelectorAll("th")]
      .find((th) => th.textContent.trim() === "Store price");
    if (!storePriceHeader) return;

    const marketValueHeader = document.createElement("th");
    marketValueHeader.dataset.marketValueColumn = "true";
    marketValueHeader.textContent = "Market value";
    marketValueHeader.title = "Drop Rate valuation; Cardmarket guide estimates are labelled separately";
    headerRow.insertBefore(marketValueHeader, storePriceHeader);
  }

  function insertPlaceholderCells(data) {
    ensureHeader();
    const rows = [...document.querySelectorAll("#inventory-body tr")];
    rows.forEach((row, index) => {
      const storePriceCell = row.querySelector('td[data-label="Store price"]');
      if (!storePriceCell) return;
      let cell = row.querySelector("td[data-market-value-cell]");
      if (!cell) {
        cell = document.createElement("td");
        cell.dataset.marketValueCell = "true";
        cell.dataset.label = "Market value";
        row.insertBefore(cell, storePriceCell);
      }
      cell.textContent = "—";
      const item = data.items[index];
      if (item) cell.dataset.inventoryId = item.id;
    });
  }

  async function hydrateMarketValues(data) {
    insertPlaceholderCells(data);
    const ids = data.items.map((item) => item.id).filter(Boolean);
    if (!ids.length) return;

    const params = new URLSearchParams();
    ids.forEach((id) => params.append("inventory_id", id));

    try {
      const result = await apiRequest(`/api/v1/inventory/market-values?${params.toString()}`);
      const values = new Map(result.items.map((item) => [item.id, item]));

      document.querySelectorAll("#inventory-body td[data-market-value-cell]").forEach((cell) => {
        const value = values.get(cell.dataset.inventoryId);
        if (!value) return;
        cell.textContent = formatGBP(value.market_value_minor);
        if(value.market_value_minor!=null && value.pricing_method==="CARDMARKET_GUIDE_V1"){
          const note=document.createElement("small");note.style.display="block";note.textContent="Cardmarket estimate";cell.append(note);
        }
        if (value.pricing_updated_at) {
          const updated = new Date(value.pricing_updated_at);
          if (!Number.isNaN(updated.getTime())) {
            cell.title = `${value.pricing_method==="CARDMARKET_GUIDE_V1"?"Cardmarket guide":"Market value"} updated ${updated.toLocaleString("en-GB")}${value.pricing_limitation?" · "+value.pricing_limitation:""}`;
          }
        }
      });
    } catch (error) {
      console.warn("Unable to load inventory market values", error);
    }
  }

  const originalRenderInventory = renderInventory;
  renderInventory = function renderInventoryWithMarketValues(data) {
    originalRenderInventory(data);
    void hydrateMarketValues(data);
  };

  ensureHeader();
})();
