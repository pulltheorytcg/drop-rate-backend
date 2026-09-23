"use strict";

(function attachMarketValueColumn() {
  function formatGBP(value) {
    if (value === null || value === undefined) return "—";
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
    marketValueHeader.title = "Current backend market estimate based on available pricing observations";
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
        if (value.pricing_updated_at) {
          const updated = new Date(value.pricing_updated_at);
          if (!Number.isNaN(updated.getTime())) {
            cell.title = `Market value updated ${updated.toLocaleString("en-GB")}`;
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
