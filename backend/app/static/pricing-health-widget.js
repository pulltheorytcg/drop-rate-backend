"use strict";
/* Founder-only live pricing telemetry from existing Supabase, no writes. */
(() => {
  const POLL_MS = 60000;
  let panel = null, timer = null, generation = 0, busy = false, access = false;
  // Reuse the existing expensive, globally cached reference-coverage endpoint.
  // At most one request every ten minutes per visible founder session.
  let catalogueCoverage = null, catalogueLastCheck = 0;
  let catalogueBusy = false, catalogueGeneration = 0;

  function element(tag, cls, text) {
    const result = document.createElement(tag);
    if (cls) result.className = cls;
    if (text !== undefined) result.textContent = text;
    return result;
  }
  const count = n => Number.isSafeInteger(n) && n >= 0 ? n.toLocaleString("en-GB") : "—";
  function time(value) {
    if (!value) return "Not recorded";
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? "Not recorded" :
      d.toLocaleString("en-GB", {dateStyle:"medium", timeStyle:"short"});
  }
  function currentUser() {
    try {return state.session?.user?.id || null;} catch (_) {return null;}
  }
  function ownerMode() {return Boolean(document.getElementById("owner-view-settings"));}
  function container() {
    return ownerMode() ? document.getElementById("owner-view-settings") :
      document.querySelector('[data-seller-view="settings"]');
  }
  function allowed() {
    if (!currentUser()) return false;
    if (!ownerMode()) return true;
    try {return access && state.access?.business_allowed === true;}
    catch (_) {return false;}
  }
  function visible() {
    return allowed() && panel && !panel.hidden && !panel.closest(".hidden");
  }

  function mount() {
    if (panel) return panel;
    const parent = container();
    if (!parent) return null;
    panel = element("section", ownerMode() ? "owner-panel pricing-health-panel" : "inventory-panel pricing-health-panel");
    panel.id = "pricing-health-panel";
    panel.setAttribute("aria-label", "Live market pricing health");
    const heading = element("div", "pricing-health-heading");
    const left = element("div");
    left.append(element("p", "eyebrow", "Drop Rate · Market intelligence"),
      element("h2", "", "Pricing engine health"));
    const button = element("button", "ghost-button compact", "↻ Refresh now");
    button.id = "pricing-health-refresh";
    button.type = "button";
    button.addEventListener("click", refresh);
    heading.append(left, button);
    const banner = element("div", "pricing-health-banner", "Checking actual pricing evidence…");
    banner.id = "pricing-health-banner";
    banner.setAttribute("role", "status");
    banner.setAttribute("aria-live", "polite");
    const metrics = element("div", "pricing-health-metrics");
    metrics.id = "pricing-health-metrics";
    const sources = element("div", "pricing-health-sources");
    sources.id = "pricing-health-sources";
    const backlog = element("div", "pricing-health-sources");
    backlog.id = "pricing-health-backlog";
    const alerts = element("div", "pricing-health-alerts");
    alerts.id = "pricing-health-alerts";
    const updated = element("p", "muted pricing-health-time", "No live check completed yet.");
    updated.id = "pricing-health-time";
    panel.append(heading,
      element("p", "muted", "Live from Supabase Pro · Refreshes every 60 seconds while open. Stored values are not necessarily UK sold-price verified."),
      banner, metrics, element("h3", "pricing-health-subheading", "Source health"), sources,
      element("h3", "pricing-health-subheading", "Catalogue valuation backlog"), backlog,
      element("h3", "pricing-health-subheading", "Action required"), alerts, updated);
    if (ownerMode()) {
      panel.hidden = true;
      // Personal seller accounts must never see founder operations.
      parent.append(panel);
    } else {
      parent.prepend(panel);
    }
    return panel;
  }
  function metric(label, value, detail) {
    const card = element("article", "pricing-health-stat");
    card.append(element("small", "", label), element("strong", "", value),
      element("small", "", detail));
    return card;
  }
  function sourceRow(label, status, note) {
    const row = element("div", "pricing-health-source");
    const copy = element("div");
    copy.append(element("strong", "", label), element("small", "", note));
    const state = element("span", "pricing-health-state", status.replaceAll("_", " "));
    state.dataset.healthState = status;
    row.append(copy, state);
    return row;
  }

  function catalogueMetric() {
    const current = catalogueCoverage?.summary?.physical_cards;
    const card = metric(
      "Catalogue price references",
      current ? count(current.priced) + " / " + count(current.total) :
        catalogueBusy ? "Checking…" : "Not checked",
      "Guide-inclusive reference coverage · not exact sold Market Values"
    );
    card.id = "pricing-health-catalogue-metric";
    return card;
  }

  async function refreshCatalogueCoverage() {
    if (!visible() || catalogueBusy ||
        (catalogueLastCheck && Date.now() - catalogueLastCheck < 600000)) return;
    const user = currentUser(), version = ++catalogueGeneration;
    catalogueBusy = true;
    catalogueLastCheck = Date.now();
    try {
      // This is the existing source/printing-specific coverage calculation,
      // never a proxy based on the 617 owned physical inventory items.
      const [result, workQueue] = await Promise.all([
        apiRequest("/api/v1/catalogue-browser/coverage"),
        apiRequest("/api/v1/pricing/coverage-work-queue"),
      ]);
      if (version !== catalogueGeneration || user !== currentUser() || !visible()) return;
      if (result?.summary?.physical_cards &&
          Number.isSafeInteger(result.summary.physical_cards.total) &&
          Number.isSafeInteger(result.summary.physical_cards.priced)) {
        catalogueCoverage = result;
      }
      renderCoverageBacklog(workQueue);
    } catch (_) {
      // Source availability and live pricing health remain independently visible.
    } finally {
      if (version === catalogueGeneration) {
        catalogueBusy = false;
        const old = document.getElementById("pricing-health-catalogue-metric");
        if (old && visible()) old.replaceWith(catalogueMetric());
      }
    }
  }

  function renderCoverageBacklog(data) {
    const target = document.getElementById("pricing-health-backlog");
    if (!target || !data) return;
    const rows = document.createDocumentFragment();
    const legacy = data.legacy_sql || {};
    const r2 = data.r2_first || {};
    rows.append(sourceRow(
      "Original SQL catalogue",
      "GUIDE_INCLUSIVE_NOT_SOLD_VERIFIED",
      count(legacy.references) + " card references · " +
      count(legacy.missing_or_ineligible_reference_prices) +
      " missing current eligible reference prices · " +
      count(legacy.guide_inclusive_current_reference_prices) +
      " with guides/quotes (NOT verified UK sold valuations)"
    ));
    rows.append(sourceRow(
      "Newer catalogues (R2-first)",
      "NOT_MEASURED",
      count(r2.stored_references_including_other_collectibles) +
      " published references (includes figures/sports) · " +
      "Market Value coverage NOT MEASURED, not assumed zero"
    ));
    for (const item of (data.groups || []).slice(0, 7)) {
      const status = item.market_value_coverage === "NOT_MEASURED"
        ? "SOURCE_ACCESS_REQUIRED" : item.priority || "REVIEW";
      const volume = item.reference_prices_missing == null
        ? count(item.reference_count) + " stored references · Market Value unmeasured"
        : count(item.reference_prices_missing) + " missing current reference prices";
      rows.append(sourceRow(
        String(item.game || "Card game") +
          (item.language ? " · " + item.language : ""),
        status,
        volume + " · " + (item.next_action || "Check exact source evidence")
      ));
    }
    target.replaceChildren(rows);
  }

  function render(data) {
    if (!panel) return;
    const banner = document.getElementById("pricing-health-banner");
    banner.dataset.healthState = data.overall_status || "UNKNOWN";
    banner.textContent = (data.overall_label || "Status unavailable") +
      " · Market Value auto-publication: " +
      (data.automation?.automatic_sold_value_publication_ready ? "eligible for separate review" : "held until sold evidence qualifies");
    const inv = data.inventory || {};
    document.getElementById("pricing-health-metrics").replaceChildren(
      metric("Active physical inventory", count(inv.active_items), "Items tracked"),
      metric("Stored Market Values", count(inv.stored_value_items),
        String(inv.stored_coverage_pct ?? 0) + "% of active items"),
      metric("Updated within 7 days", count(inv.updated_last_7d), "Not necessarily sold-verified"),
      metric("Missing Market Values", count(inv.missing_value_items), "Needs eligible actual-sale evidence"),
      catalogueMetric()
    );
    const rows = document.createDocumentFragment();
    for (const item of data.sources || []) {
      const notes = [
        item.detail,
        item.stored_observations == null ? null : count(item.stored_observations) + " historical records",
        item.normalized_uk_sold_observations == null ? null :
          count(item.normalized_uk_sold_observations) + " qualifying UK sold records",
        item.new_normalized_24h == null ? null :
          count(item.new_normalized_24h) + " qualifying arrivals in 24h",
        item.last_ingested_at ? "Last import: " + time(item.last_ingested_at) : null,
        item.last_run?.status ? "Last run: " + item.last_run.status +
          " (" + time(item.last_run.completed_at) + ")" : null,
      ].filter(Boolean).join(" · ");
      rows.append(sourceRow(item.label || item.source || "Source", item.status || "UNKNOWN", notes));
    }
    document.getElementById("pricing-health-sources").replaceChildren(rows);
    const alertBox = document.getElementById("pricing-health-alerts");
    alertBox.replaceChildren();
    for (const entry of (data.alerts || []).slice(0, 8)) {
      const alert = element("p", "pricing-health-alert", entry.text || "Review source status");
      alert.dataset.severity = entry.severity || "INFO";
      alertBox.append(alert);
    }
    if (!alertBox.childElementCount) alertBox.append(element("p", "muted", "No current evidence alerts."));
    const automation = data.automation || {};
    document.getElementById("pricing-health-time").textContent =
      "Last checked: " + time(data.checked_at) +
      " · Market ingestion: " + (automation.market_ingestion_enabled ? "enabled" : "disabled") +
      " · Bulk hold: " + (automation.bulk_refresh_held ? "active" : "inactive") +
      " · Unattended Product Research: " +
      (automation.unattended_product_research_verified ? "verified" : "not verified");
  }

  function stop() {
    generation += 1;
    catalogueGeneration += 1;
    catalogueCoverage = null;
    catalogueLastCheck = 0;
    catalogueBusy = false;
    if (timer !== null) { window.clearInterval(timer); timer = null; }
    busy = false;
    if (!panel) return;
    panel.hidden = ownerMode();
    document.getElementById("pricing-health-banner").textContent =
      "Sign in as an approved founder to view pricing health.";
    for (const id of ["pricing-health-metrics","pricing-health-sources","pricing-health-backlog","pricing-health-alerts"]) {
      document.getElementById(id)?.replaceChildren();
    }
  }

  async function refresh() {
    if (!visible() || busy) return;
    const user = currentUser(), version = ++generation;
    busy = true;
    const button = document.getElementById("pricing-health-refresh");
    if (button) button.disabled = true;
    try {
      const data = await apiRequest("/api/v1/pricing/health");
      if (generation !== version || user !== currentUser() || !visible()) return;
      render(data);
      void refreshCatalogueCoverage();
    } catch (error) {
      if (generation !== version || user !== currentUser() || !visible()) return;
      const banner = document.getElementById("pricing-health-banner");
      banner.dataset.healthState = "UNKNOWN";
      banner.textContent = "Pricing health unavailable: " +
        (error.message || "Could not read source telemetry");
    } finally {
      if (generation === version) busy = false;
      if (button) button.disabled = false;
    }
  }
  function tick() {if (visible()) refresh();}
  function start() {
    mount();
    if (!panel || !allowed()) return;
    if (ownerMode()) panel.hidden = false;
    if (timer === null) timer = window.setInterval(tick, POLL_MS);
    tick();
  }
  function init() {
    mount();
    if (ownerMode()) {
      try {access = state.access?.business_allowed === true;} catch (_) {access = false;}
      document.addEventListener("hub:access-verified", event => {
        access = event.detail?.access?.business_allowed === true;
        if (!access) stop(); else start();
      });
      document.addEventListener("hub:founder-access", event => {
        access = event.detail?.allowed === true;
        if (!access) stop(); else start();
      });
      document.addEventListener("owner-view-changed", start);
      window.addEventListener("hub-session-cleared", () => {access = false; stop();});
    } else {
      document.addEventListener("seller-view-changed", start);
      document.addEventListener("hub-ready", start);
      window.addEventListener("hub-session-cleared", stop);
    }
    start();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
  window.DropRatePricingHealth = {refresh, start, stop};
})();
