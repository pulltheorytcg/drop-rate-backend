/* Owner-scoped founder media review panel.
 * Renders only data from /api/v1/action-required (server RLS + owner auth).
 * Never fetches third-party media, approves assets or changes inventory.
 */
(function (global) {
  "use strict";

  const PREVIEW_ROWS = 8;
  const MAX_LOADED_ROWS = 50;
  const SEVERITIES = new Set(["LOW", "MEDIUM", "HIGH", "CRITICAL"]);

  function element(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined && value !== null) node.textContent = String(value);
    return node;
  }

  function stockCode(item) {
    const code = item && item.metadata && item.metadata.inventory_code;
    return item && item.entity_type === "INVENTORY_ITEM"
      && typeof code === "string"
      && /^INV-[A-Z0-9-]{12,80}$/.test(code) ? code : null;
  }

  function itemNode(item, onFind) {
    const node = element("article", "media-review-item");
    const headline = element("div", "media-review-item-heading");
    const title = element("strong", "media-review-title", item.title || "Media review required");
    const severity = SEVERITIES.has(item.severity) ? item.severity : "MEDIUM";
    const badge = element("span", "media-review-severity media-review-severity-" + severity.toLowerCase(), severity);
    headline.append(title, badge);

    const detail = element("p", "media-review-detail", item.detail || "A media review is needed.");
    const action = element("p", "media-review-action", item.recommended_action || "Review the item before publication.");
    const code = stockCode(item);
    node.append(headline, detail, action);

    if (code && typeof onFind === "function") {
      const controls = element("div", "media-review-controls");
      controls.append(element("span", "media-review-stock-code", code));
      const button = element("button", "media-review-find", "Find in inventory");
      button.type = "button";
      button.setAttribute("aria-label", "Find " + code + " in inventory");
      button.addEventListener("click", () => onFind(code));
      controls.append(button);
      node.append(controls);
    }
    return node;
  }

  function render(data, onFind) {
    if (!data || !Array.isArray(data.items)) throw new TypeError("Invalid media-review response");
    const container = document.getElementById("media-review-list");
    const counter = document.getElementById("media-review-count");
    const message = document.getElementById("media-review-feedback");
    if (!container || !counter || !message) return;
    const all = data.items.filter(item => item && typeof item === "object").slice(0, MAX_LOADED_ROWS);
    const total = Number.isSafeInteger(data.total) && data.total >= 0 ? data.total : all.length;
    counter.textContent = total.toLocaleString("en-GB") + " open";
    message.textContent = total > all.length
      ? "Showing the first " + all.length + " of " + total + " open media reviews."
      : "Owner-specific queue. Review media before approving or publishing it.";

    function draw(expanded) {
      container.replaceChildren();
      const visible = expanded ? all : all.slice(0, PREVIEW_ROWS);
      if (visible.length === 0) {
        container.append(element("p", "media-review-empty", "No open media reviews for this owner."));
        return;
      }
      for (const item of visible) container.append(itemNode(item, onFind));
      if (all.length > PREVIEW_ROWS) {
        const toggle = element("button", "media-review-expand",
          expanded ? "Show fewer" : "Show more (" + (all.length - PREVIEW_ROWS) + ")");
        toggle.type = "button";
        toggle.setAttribute("aria-expanded", String(expanded));
        toggle.addEventListener("click", () => draw(!expanded));
        container.append(toggle);
      }
    }
    draw(false);
  }

  function showError() {
    const list = document.getElementById("media-review-list");
    const feedback = document.getElementById("media-review-feedback");
    if (list) list.replaceChildren();
    if (feedback) feedback.textContent = "Media review queue unavailable. Refresh to retry.";
  }

  function clear() {
    const list = document.getElementById("media-review-list");
    const count = document.getElementById("media-review-count");
    const feedback = document.getElementById("media-review-feedback");
    if (list) list.replaceChildren();
    if (count) count.textContent = "—";
    if (feedback) feedback.textContent = "";
  }

  global.DropRateMediaReviewQueue = Object.freeze({render, showError, clear});
})(window);
