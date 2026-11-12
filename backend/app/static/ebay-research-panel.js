"use strict";

// Founder-only research assistance. This does not scrape eBay, store credentials,
// import sales into Supabase or change a customer's Market Value or Store Price.
(() => {
  const field = (id) => document.getElementById(id);
  const local = {code: null, target: null, request: 0, userId: null};

  function report(message, kind = "") {
    const el = field("ebay-research-feedback");
    if (!el) return;
    el.textContent = message;
    el.className = "message panel-message" + (kind ? " " + kind : "");
  }

  function clear() {
    local.request += 1;
    local.code = null;
    local.target = null;
    local.userId = null;
    const link = field("ebay-research-open");
    if (link) { link.classList.add("hidden"); link.removeAttribute("href"); }
    const rows = field("ebay-research-rows");
    if (rows) rows.replaceChildren();
    const lookup = field("ebay-research-identity");
    if (lookup) lookup.textContent = "No card selected.";
    const result = field("ebay-research-result");
    if (result) result.textContent = "";
    report();
  }

  function textInput(labelText, name, type = "text", placeholder = "") {
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement("input");
    input.name = name;
    input.type = type;
    input.placeholder = placeholder;
    input.maxLength = 300;
    input.autocomplete = "off";
    if (type === "number") { input.min = "0"; input.step = "0.01"; }
    label.append(input);
    return label;
  }

  function renderFiveRowInputs() {
    const container = field("ebay-research-rows");
    container.replaceChildren();
    for (let i = 0; i < 5; i += 1) {
      const row = document.createElement("fieldset");
      row.className = "ebay-research-row";
      const legend = document.createElement("legend");
      legend.textContent = "Completed sale " + (i + 1);
      row.append(legend);
      const grid = document.createElement("div");
      grid.className = "ebay-research-grid";
      grid.append(
        textInput("eBay item number", "item_id", "text", "Item ID from Product Research"),
        textInput("Listing title", "title", "text", "Exact printed card, set and finish"),
        textInput("Sale date", "sold_at", "date"),
        textInput("Actual item price paid (£)", "price_gbp", "number", "Not the asking price"),
        textInput("Postage (£, optional)", "shipping_gbp", "number", "Leave blank if unknown"),
        textInput("Observed condition", "condition_raw", "text", "NM, PSA grade, etc."),
      );
      row.append(grid);
      const confirmation = document.createElement("label");
      confirmation.className = "ebay-research-confirm";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.name = "confirmed";
      confirmation.append(checkbox, document.createTextNode(
        " I checked the actual paid price and UK item location in eBay Product Research, plus the exact printing."
      ));
      row.append(confirmation);
      container.append(row);
    }
  }

  function capture() {
    // Never render an old owner's results after sign-out or account switch.
    return {request: ++local.request, userId: state.session?.user?.id || null};
  }
  function current(check) {
    return check.request === local.request &&
      Boolean(check.userId) &&
      state.session?.user?.id === check.userId;
  }

  async function loadSearch() {
    const button = field("ebay-research-lookup");
    const code = (field("ebay-research-code")?.value || "").trim().toUpperCase();
    clear();
    if (!/^INV-[A-Z0-9-]{6,56}$/.test(code)) {
      report("Enter your physical Inventory ID, for example INV- followed by the unique code.", "error");
      return;
    }
    const check = capture();
    button.disabled = true;
    report("Checking your inventory and preparing the eBay UK research link…");
    try {
      const result = await apiRequest(
        "/api/v1/pricing/ebay-research/inventory/" + encodeURIComponent(code) + "/search"
      );
      if (!current(check)) return;
      const url = new URL(result.sold_search_url);
      if (url.protocol !== "https:" || url.hostname !== "www.ebay.co.uk") {
        throw new Error("Research link failed the eBay host check.");
      }
      local.target = result.target;
      local.code = result.inventory_code;
      local.userId = check.userId;
      field("ebay-research-identity").textContent = [
        result.target.game, result.target.name, result.target.set_name,
        result.target.card_number, result.target.variant, result.target.language,
        result.target.grading_company && (result.target.grading_company + " " + result.target.grade),
        result.target.condition
      ].filter(Boolean).join(" · ");
      const link = field("ebay-research-open");
      link.href = url.toString();
      link.classList.remove("hidden");
      renderFiveRowInputs();
      report("Ready. Open eBay in your signed-in browser, then review five actual completed sale prices.");
    } catch (error) {
      if (current(check)) report(error.message || "Inventory lookup failed.", "error");
    } finally {
      if (current(check)) button.disabled = false;
    }
  }

  function reviewedRows() {
    const rows = [...field("ebay-research-rows").querySelectorAll("fieldset")];
    if (rows.length !== 5 || !local.target) throw new Error("Prepare a valid owned card first.");
    return rows.map((row, index) => {
      const read = (name) => row.querySelector('[name="' + name + '"]')?.value.trim() || "";
      if (!row.querySelector('[name="confirmed"]')?.checked) {
        throw new Error("Sale " + (index + 1) + ": verify its actual paid price, UK location and exact printing.");
      }
      for (const name of ["item_id", "title", "sold_at", "price_gbp"]) {
        if (!read(name)) throw new Error("Sale " + (index + 1) + ": " + name + " is required.");
      }
      if (!local.target.grading_company && !read("condition_raw")) {
        throw new Error("Sale " + (index + 1) + ": observed raw condition is required.");
      }
      return {
        source: "EBAY_PRODUCT_RESEARCH",
        sale_price_basis: "ACTUAL_PAID_PRICE",
        item_id: read("item_id"),
        title: read("title"),
        sold_at: read("sold_at"),
        price_gbp: read("price_gbp"),
        shipping_gbp: read("shipping_gbp") || null,
        currency: "GBP",
        item_country: "GB",
        condition_raw: read("condition_raw") || null,
        set_name: local.target.set_name,
        card_number: local.target.card_number,
        variant: local.target.variant,
        language: local.target.language,
      };
    });
  }

  async function preview() {
    const button = field("ebay-research-preview");
    if (!local.code || !local.target) { report("Select an inventory item first.", "error"); return; }
    let sales;
    try { sales = reviewedRows(); }
    catch (error) { report(error.message, "error"); return; }
    const check = capture();
    button.disabled = true;
    report("Checking exact card identity and reviewed sales…");
    try {
      const result = await apiRequest(
        "/api/v1/pricing/ebay-research/inventory/" + encodeURIComponent(local.code) + "/preview",
        {method: "POST", body: JSON.stringify({sales})},
      );
      if (!current(check)) return;
      const resultBox = field("ebay-research-result");
      if (result.status === "REVIEW_REQUIRED" &&
          result.candidate_median_item_price_minor != null) {
        const candidate = (result.candidate_median_item_price_minor / 100).toLocaleString(
          "en-GB", {style: "currency", currency: "GBP"}
        );
        resultBox.textContent = "Reviewed sales candidate: " + candidate +
          ". This is NOT a verified Market Value and has not been published.";
      } else {
        resultBox.textContent = "Market Value unavailable: insufficient exact, recent completed-sale evidence.";
      }
      const excluded = Object.entries(result.excluded_reasons || {}).map(
        ([reason, count]) => reason + ": " + count
      ).join(" · ");
      report(result.eligible_exact_count + " exact sales checked. " +
        (excluded ? "Excluded: " + excluded + ". " : "") +
        "No database, Shopify or Store Price changes.");
    } catch (error) {
      if (current(check)) report(error.message || "Research preview failed.", "error");
    } finally {
      if (current(check)) button.disabled = false;
    }
  }

  const start = () => {
    if (!field("ebay-research-lookup")) return;
    field("ebay-research-lookup").addEventListener("click", loadSearch);
    field("ebay-research-preview").addEventListener("click", preview);
    field("logout-button")?.addEventListener("click", clear);
    field("ebay-research-code")?.addEventListener("input", () => {
      if (local.code) clear();
    });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
