"use strict";
const {JSDOM} = require("jsdom");
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");

const assets = path.resolve(__dirname, "../../backend/app/static");
const html = fs.readFileSync(path.join(assets, "index.html"), "utf8");
const app = fs.readFileSync(path.join(assets, "app.js"), "utf8");
const source = fs.readFileSync(path.join(assets, "media-review-queue.js"), "utf8");

assert.match(html, /id="media-review-list"/);
assert.match(html, /id="media-review-count"/);
assert.match(html, /\/assets\/media-review-queue\.css\?v=tier1-20261110/);
assert.match(html, /\/assets\/media-review-queue\.js\?v=tier1-20261110/);
assert.ok(
  html.indexOf("/assets/media-review-queue.js") < html.indexOf("/assets/app.js"),
  "Owner media queue renderer must load before the founder controller"
);
assert.match(app, /\/api\/v1\/action-required\?category=MEDIA&status=OPEN&limit=50/);
assert.match(app, /mediaReviewRequestGeneration \+= 1;/);
assert.match(app, /requestGeneration !== mediaReviewRequestGeneration/);
assert.match(app, /loadReadiness\(\), loadBrandOptions\(\), loadInventory\(\), loadMediaActionRequired\(\)/);
assert.match(app, /DropRateMediaReviewQueue\.showError\(\)/);

const dom = new JSDOM(`<!doctype html><body>
  <span id="media-review-count">—</span>
  <p id="media-review-feedback"></p>
  <div id="media-review-list"></div>
</body>`, {url: "https://app.droprate.co.uk/founders", runScripts: "outside-only"});
const w = dom.window;
w.eval(source);
const panel = w.DropRateMediaReviewQueue;
assert.ok(panel && typeof panel.render === "function");
const list = w.document.getElementById("media-review-list");
const count = w.document.getElementById("media-review-count");
const feedback = w.document.getElementById("media-review-feedback");
const codes = [];
const validCode = "INV-0753B8ACB97443D7ABC14BAD1400E414";

const rows = Array.from({length: 12}, (_, i) => ({
  entity_type: "INVENTORY_ITEM",
  title: i === 0 ? "<img src=x onerror=alert(1)> Card review" : "Card #" + i,
  detail: i === 0 ? "<script>alert(1)</script> pending review" : "No verified media",
  recommended_action: i === 0 ? "<b>Photograph the real item</b>" : "Check exact art and rights",
  severity: i === 0 ? "HIGH" : "MEDIUM",
  metadata: {inventory_code: i === 0 ? validCode : "INV-ABCDEF123456" + i},
}));

panel.render({items: rows, total: 16}, code => codes.push(code));
assert.equal(count.textContent, "16 open", "Count must use the owner-scoped API total");
assert.match(feedback.textContent, /Showing the first 12 of 16/);
assert.equal(list.querySelectorAll("article.media-review-item").length, 8, "Initial view is bounded");
assert.equal(list.querySelector("img"), null, "Untrusted titles are never parsed as markup");
assert.equal(list.querySelector("script"), null, "Untrusted task details are plain text");
assert.match(list.textContent, /<img src=x onerror=alert\(1\)>/);
assert.match(list.textContent, /<b>Photograph the real item<\/b>/);

const firstFind = list.querySelector(".media-review-find");
assert.ok(firstFind, "Exact physical inventory has a find action");
firstFind.click();
assert.deepEqual(codes, [validCode], "Find passes only the exact inventory code");

const expand = list.querySelector(".media-review-expand");
assert.ok(expand);
assert.equal(expand.getAttribute("aria-expanded"), "false");
expand.click();
assert.equal(list.querySelectorAll("article.media-review-item").length, 12);
assert.equal(list.querySelector(".media-review-expand").getAttribute("aria-expanded"), "true");
list.querySelector(".media-review-expand").click();
assert.equal(list.querySelectorAll("article.media-review-item").length, 8);

panel.render({items: [{
  title: "Bad external reference", severity: "CRITICAL", entity_type: "CATALOGUE_CARD",
  metadata: {inventory_code: validCode},
}]}, code => codes.push(code));
assert.equal(list.querySelector(".media-review-find"), null, "Catalogue cards cannot navigate as physical stock");

panel.render({items: [{
  title: "Malformed inventory input", severity: "INVALID", entity_type: "INVENTORY_ITEM",
  metadata: {inventory_code: "javascript:alert(1)"},
}]}, code => codes.push(code));
assert.equal(list.querySelector(".media-review-find"), null, "Malformed IDs cannot drive inventory navigation");
assert.equal(list.querySelector(".media-review-severity").textContent, "MEDIUM", "Unknown severity fails closed");

panel.render({items: [], total: 0});
assert.match(list.textContent, /No open media reviews/);
assert.equal(count.textContent, "0 open");
assert.throws(() => panel.render({items: "not-an-array"}), /Invalid media-review response/);

panel.showError();
assert.match(feedback.textContent, /unavailable/);
assert.equal(list.children.length, 0);
panel.clear();
assert.equal(list.children.length, 0);
assert.equal(count.textContent, "—");
assert.equal(feedback.textContent, "");
w.close();
console.log("PASS: founder Action Required media queue is owner-fed, bounded, plain-text safe, navigable and logout-cleared");
