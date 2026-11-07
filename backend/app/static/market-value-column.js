"use strict";

(function attachMarketValueColumn() {
  function formatGBP(value) {
    if (value === null || value === undefined) return "Value unavailable";
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
    marketValueHeader.textContent = "Value";
    marketValueHeader.title = "Drop Rate valuation; source and evidence details are available in each item";
    headerRow.insertBefore(marketValueHeader, storePriceHeader);
  }

  function renderMarketValues(data) {
    ensureHeader();
    const rows = [...document.querySelectorAll("#inventory-body tr")];
    rows.forEach((row, index) => {
      const storePriceCell = row.querySelector('td[data-label="Store price"]');
      if (!storePriceCell) return;
      let cell = row.querySelector("td[data-market-value-cell]");
      if (!cell) {
        cell = document.createElement("td");
        cell.dataset.marketValueCell = "true";
        cell.dataset.label = "Value";
        row.insertBefore(cell, storePriceCell);
      }
      const item = (data.display_items || data.items)[index];
      if (!item) return;
      cell.dataset.inventoryId = item.id;
      // The authorized inventory response already contains the shared price.
      // Render it synchronously; another request used to replace it with a dash.
      cell.textContent = window.DropRateReferenceValue.text(item, formatGBP);
      cell.title = window.DropRateReferenceValue.description(item);
    });
  }

  const originalRenderInventory = renderInventory;
  renderInventory = function renderInventoryWithMarketValues(data) {
    originalRenderInventory(data);
    renderMarketValues(data);
  };

  ensureHeader();
})();
