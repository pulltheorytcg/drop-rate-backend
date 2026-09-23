"use strict";

// Inventory market values are read from the deterministic pricing overview.
// A missing valuation stays unknown (—); it is never rendered as £0.
const marketValuesByInventoryId = new Map();
let marketValuesLoadedAt = 0;
const MARKET_VALUE_CACHE_MS = 60_000;

function ensureMarketValueHeader() {
  const headerRow = document.querySelector("#inventory-body")?.closest("table")?.querySelector("thead tr");
  if (!headerRow || headerRow.querySelector("[data-market-value-header]")) return;
  const storePriceHeader = [...headerRow.querySelectorAll("th")].find((th) => th.textContent.trim() === "Store price");
  if (!storePriceHeader) return;
  const th = document.createElement("th");
  th.dataset.marketValueHeader = "true";
  th.textContent = "Market value";
  headerRow.insertBefore(th, storePriceHeader);
}

async function loadAllMarketValues(force = false) {
  const now = Date.now();
  if (!force && marketValuesLoadedAt && now - marketValuesLoadedAt < MARKET_VALUE_CACHE_MS) return;

  const next = new Map();
  const limit = 200;
  let offset = 0;
  while (true) {
    const data = await apiRequest(`/api/v1/pricing/inventory?limit=${limit}&offset=${offset}`);
    const items = data.items || [];
    items.forEach((item) => next.set(item.id, item.market_value_minor));
    if (items.length < limit) break;
    offset += limit;
  }

  marketValuesByInventoryId.clear();
  next.forEach((value, key) => marketValuesByInventoryId.set(key, value));
  marketValuesLoadedAt = now;
}

const renderInventoryWithoutMarketValue = renderInventory;
renderInventory = function renderInventoryWithMarketValue(data) {
  ensureMarketValueHeader();
  const enriched = {
    ...data,
    items: data.items.map((item) => ({
      ...item,
      market_value_minor: marketValuesByInventoryId.has(item.id)
        ? marketValuesByInventoryId.get(item.id)
        : null,
    })),
  };

  renderInventoryWithoutMarketValue(enriched);

  const rows = [...document.querySelectorAll("#inventory-body tr")];
  rows.forEach((row, index) => {
    const item = enriched.items[index];
    const storePriceCell = [...row.querySelectorAll("td")].find((td) => td.dataset.label === "Store price");
    if (!item || !storePriceCell) return;
    const cell = textCell("Market value", money(item.market_value_minor, "GBP"), "market-value-cell");
    row.insertBefore(cell, storePriceCell);
  });
};

const loadInventoryWithoutMarketValues = loadInventory;
loadInventory = async function loadInventoryWithMarketValues() {
  try {
    await loadAllMarketValues();
  } catch (_error) {
    // Inventory must remain usable if pricing data is temporarily unavailable.
    marketValuesByInventoryId.clear();
  }
  return loadInventoryWithoutMarketValues();
};

ensureMarketValueHeader();
