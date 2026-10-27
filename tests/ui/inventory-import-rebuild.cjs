"use strict";
// Founder DOM and production JS with a synthetic API. This is not a live login.
const assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.join(__dirname, "../../backend/app/static");
const source = fs.readFileSync(path.join(root, "inventory-imports.js"), "utf8");
const batchId = "330b709b-58b4-4113-aee4-80ce1bfd6148";
const oldId = "cfac8d65-cb24-4bee-b206-8b7828229d67";
const newId = "fbb140a4-5f83-442d-9e72-ffb345c71ce9";
const original = "Name,CorrectName,Quantity,Copies\nBefore,Correct card,1,2\n";
const pause = async () => { for (let i = 0; i < 8; i += 1) await new Promise(setImmediate); };

function fixture(options = {}) {
  const dom = new JSDOM('<!doctype html><body><div><button id="refresh-button">Refresh</button></div><div id="inventory-message"></div></body>', {
    url: "https://drop-rate.test/dashboard", runScripts: "outside-only",
  });
  const w = dom.window, doc = w.document, context = dom.getInternalVMContext();
  const calls = [];
  let exists = Boolean(options.existing), version = 1, rebuilt = false, release = null;
  let rows = [{ id: oldId, source_row: 2, quantity: 1, status: "REVIEW", issues: ["catalogue_not_found"],
    normalized_record: { name: "Before", quantity: 1 }, catalogue_id: null }];
  if (options.candidateStatus) rows[0].status = options.candidateStatus;
  const status = options.status || "PREVIEW";
  const summary = () => options.summary || ({
    candidate_count: rows.length,
    ready_units: rows.filter(row => row.status === "READY").reduce((sum, row) => sum + row.quantity, 0),
    review_rows: rows.filter(row => row.status === "REVIEW").length,
    skipped_rows: rows.filter(row => row.status === "SKIPPED").length,
  });
  const detail = () => ({
    batch: { id: batchId, version, status, filename: options.filename || "original.csv",
      adapter: "GENERIC_CSV", source_rows: 1, physical_units: rebuilt ? 2 : 1, warnings: [],
      automatic_intake: options.automatic || false, last_auto_apply_version: options.lastAuto || null,
      committed_at: options.committedAt || null },
    summary: summary(), candidates: structuredClone(rows), rebuild_enabled: options.enabled !== false,
  });
  w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  w.HTMLDialogElement.prototype.close = function () { this.open = false; this.dispatchEvent(new w.Event("close")); };
  w.confirm = () => true;
  w.__api = async (url, init = {}) => {
    const method = init.method || "GET", body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url, method, body });
    if (url === "/api/v1/action-required/summary") return { items: [] };
    if (url === "/api/v1/imports?limit=8") return { items: exists ? [detail().batch] : [] };
    if (url === "/api/v1/imports/preview") {
      if (exists) throw Object.assign(new Error("This exact file has already been imported or previewed"), {
        status: 409, detail: { batch_id: batchId, status },
      });
      exists = true;
      return { batch_id: batchId, version, source_rows: 1, physical_units: 1, ...summary(), candidates: [] };
    }
    if (url === "/api/v1/imports/" + batchId && method === "GET") {
      if (rebuilt && options.failReadback) throw new Error("Readback unavailable");
      return detail();
    }
    if (url === "/api/v1/imports/" + batchId + "/rebuild") {
      assert.equal(body.version, version);
      if (options.rejectRebuild) throw Object.assign(new Error("Select the original content"), { status: 409 });
      version += 1; rebuilt = true;
      rows = [{ ...rows[0], id: newId, status: "REVIEW", quantity: 2,
        normalized_record: { name: "Correct card", quantity: 2 } }];
      if (options.delay) await new Promise(resolve => { release = resolve; });
      if (options.loseResponse) throw new Error("Response interrupted");
      return { batch_id: batchId, version, rebuilt: true, review_edits_reset: true, created_count: 0, candidates: [] };
    }
    if (url.includes("/candidates/") && url.endsWith("/skip")) {
      assert.ok(url.includes(newId), "Review must use the replacement candidate ID");
      assert.equal(body.version, version);
      rows[0].status = "SKIPPED"; version += 1;
      return { version, candidate: rows[0], summary: summary() };
    }
    throw new Error("Unexpected API request " + method + " " + url);
  };
  vm.runInContext(
    'const byId = id => document.getElementById(id);' +
    'const emptyToNull = value => value.trim() || null;' +
    'function showMessage(id, text="", kind=""){byId(id).textContent=text;byId(id).dataset.kind=kind;}' +
    'async function apiRequest(url,init){return window.__api(url,init);}' +
    'async function reloadDashboard(){};', context);
  vm.runInContext(source, context);
  const run = code => vm.runInContext(code, context);
  return {
    w, doc, calls, run, close: () => w.close(), release: () => release?.(),
    get: id => doc.getElementById(id),
    hidden: id => doc.getElementById(id).classList.contains("hidden"),
    open: async () => { run("openInventoryImport()"); await pause(); },
    resume: async () => { await run("resumeInventoryImport(" + JSON.stringify(batchId) + ")"); await pause(); },
    file: async (name = "original.csv", content = original, customText = null) => {
      const file = new w.File([content], name, { type: "text/csv" });
      Object.defineProperty(file, "text", { value: customText || (async () => content) });
      const input = doc.getElementById("import-file");
      Object.defineProperty(input, "files", { configurable: true, value: [file] });
      input.dispatchEvent(new w.Event("change", { bubbles: true }));
      await pause();
    },
    click: async id => { doc.getElementById(id).click(); await pause(); },
    preview: async () => {
      doc.getElementById("inventory-import-form").dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
      await pause();
    },
    posts: () => calls.filter(call => call.method === "POST"),
  };
}

(async () => {
  let checks = 0;
  {
    const f = fixture(); await f.open();
    await f.file("custom.tsv", '\uFEFF" Card title "\t"Card, number"\tCopies\nOne\t001\t2\n');
    f.doc.querySelector('[data-import-field="name"]').value = " Card title ";
    f.doc.querySelector('[data-import-field="quantity"]').value = "Copies";
    f.get("import-adapter").value = "GENERIC_CSV";
    await f.preview();
    assert.deepEqual(f.posts()[0].body.column_mapping, { name: " Card title ", quantity: "Copies" });
    assert.equal(f.posts()[0].body.filename, "custom.tsv");
    assert.equal(f.posts().length, 1);
    assert.equal(f.hidden("import-rebuild-button"), false);
    f.close(); checks += 1;
  }
  {
    const f = fixture({ existing: true }); await f.open(); await f.file();
    f.doc.querySelector('[data-import-field="name"]').value = "CorrectName";
    f.doc.querySelector('[data-import-field="quantity"]').value = "Copies";
    f.get("import-default-game").value = "Pokemon";
    await f.preview();
    assert.equal(f.posts().length, 1, "A duplicate upload only reopens the stored preview");
    assert.match(f.get("import-message").textContent, /choose Rebuild preview/);
    await f.preview();
    assert.equal(f.posts().length, 1, "Enter on an active preview cannot rebuild or create another batch");
    await f.click("import-rebuild-button");
    const rebuild = f.posts().find(call => call.url.endsWith("/rebuild"));
    assert.equal(rebuild.body.version, 1);
    assert.equal(rebuild.body.content, original);
    assert.deepEqual(rebuild.body.column_mapping, { name: "CorrectName", quantity: "Copies" });
    assert.equal(rebuild.body.default_game, "Pokemon");
    assert.equal(f.run("activeImportPreview.batch_id"), batchId);
    assert.equal(f.run("activeImportPreview.version"), 2);
    assert.equal(f.run("activeImportPreview.candidates[0].id"), newId);
    assert.match(f.get("import-message").textContent, /no inventory has been added/);
    const skip = [...f.get("import-preview-list").querySelectorAll("button")].find(button => button.textContent === "Skip row");
    skip.click(); await pause();
    assert.ok(f.posts().at(-1).url.includes(newId));
    assert.equal(f.posts().at(-1).body.version, 2);
    f.close(); checks += 1;
  }
  {
    const f = fixture({ existing: true }); await f.open();
    const open = [...f.get("import-recent-list").querySelectorAll("button")].find(button => button.textContent === "Open preview");
    open.click(); await pause();
    assert.equal(f.posts().length, 0);
    assert.equal(f.get("import-rebuild-button").disabled, true);
    await f.file("renamed.csv");
    assert.equal(f.get("import-rebuild-button").disabled, false);
    await f.click("import-rebuild-button");
    assert.equal(f.posts()[0].body.filename, "renamed.csv");
    assert.equal(f.run("activeImportPreview.filename"), "original.csv");
    f.close(); checks += 1;
  }
  for (const options of [{ enabled: false }, { automatic: true }, { lastAuto: 4 },
    { status: "COMMITTED" }, { committedAt: "2026-10-27T00:00:00Z" }, { candidateStatus: "COMMITTED" }]) {
    const f = fixture({ existing: true, ...options }); await f.open(); await f.resume(); await f.file();
    assert.equal(f.hidden("import-rebuild-button"), true);
    await f.run("rebuildInventoryImport()");
    assert.equal(f.posts().length, 0);
    f.close(); checks += 1;
  }
  {
    const f = fixture({ existing: true, delay: true }); await f.open(); await f.resume(); await f.file();
    await f.click("import-rebuild-button");
    assert.equal(f.get("import-commit-button").disabled, true);
    assert.equal(f.get("import-file").disabled, true);
    await f.run("rebuildInventoryImport()");
    assert.equal(f.posts().length, 1, "A double click cannot send a second rebuild");
    f.release(); await pause();
    assert.equal(f.run("activeImportPreview.version"), 2);
    f.close(); checks += 1;
  }
  {
    const f = fixture({ existing: true, delay: true }); await f.open(); await f.resume(); await f.file();
    await f.click("import-rebuild-button");
    f.get("inventory-import-dialog").close(); await f.open();
    f.release(); await pause();
    assert.equal(f.run("activeImportPreview"), null);
    assert.equal(f.hidden("import-rebuild-button"), true);
    assert.equal(f.get("import-preview-list").children.length, 0, "A late result must not repaint a new dialog");
    f.close(); checks += 1;
  }
  {
    const f = fixture({ existing: true, loseResponse: true }); await f.open(); await f.resume(); await f.file();
    await f.click("import-rebuild-button");
    assert.equal(f.run("activeImportPreview.version"), 2);
    assert.equal(f.run("activeImportPreview.candidates[0].id"), newId);
    assert.match(f.get("import-message").textContent, /saved preview has been reloaded/);
    await f.click("import-rebuild-button");
    assert.equal(f.posts()[1].body.version, 2);
    f.close(); checks += 1;
  }
  {
    const f = fixture({ existing: true, failReadback: true }); await f.open(); await f.resume(); await f.file();
    await f.click("import-rebuild-button");
    assert.equal(f.run("activeImportPreview"), null);
    assert.equal(f.get("import-preview-list").children.length, 0);
    assert.equal(f.hidden("import-commit-button"), true);
    assert.match(f.get("import-message").textContent, /Reopen it from Recent import batches/);
    f.close(); checks += 1;
  }
  {
    const f = fixture({ existing: true, rejectRebuild: true }); await f.open(); await f.resume(); await f.file();
    await f.click("import-rebuild-button");
    assert.equal(f.run("activeImportPreview.version"), 1);
    assert.equal(f.run("activeImportPreview.candidates[0].id"), oldId);
    assert.match(f.get("import-message").textContent, /Select the original content/);
    f.close(); checks += 1;
  }
  {
    const f = fixture({ existing: true, candidateStatus: "READY",
      summary: { candidate_count: 6000, ready_units: 5998, review_rows: 2, skipped_rows: 0 } });
    await f.open(); await f.resume();
    assert.equal(f.hidden("import-commit-button"), true, "Rows beyond the rendered list must still block commit");
    assert.match(f.get("import-summary").textContent, /2 rows require review/);
    assert.match(f.get("import-preview-list").textContent, /full batch remains stored/);
    f.close(); checks += 1;
  }
  {
    const f = fixture(); await f.open(); let release;
    await f.file("old.csv", "Old\nx\n", () => new Promise(resolve => { release = resolve; }));
    await f.file("new.csv", '"<img src=x onerror=alert(1)>",New\nx,y\n');
    release("Old\nx\n"); await pause();
    const mapping = f.doc.querySelector('[data-import-field="name"]');
    assert.deepEqual([...mapping.options].map(option => option.value), ["", "<img src=x onerror=alert(1)>", "New"]);
    assert.equal(f.get("import-column-fields").querySelector("img"), null);
    f.close(); checks += 1;
  }
  {
    // The production API reader must retain the exact duplicate batch identity.
    const source = fs.readFileSync(path.join(root, "app.js"), "utf8");
    const context = vm.createContext({ errorMessage: data => data.detail.message });
    vm.runInContext(source.slice(source.indexOf("async function readJson("), source.indexOf("async function authRequest(")), context);
    context.response = { ok: false, status: 409,
      json: async () => ({ detail: { message: "Already previewed", batch_id: batchId, status: "PREVIEW" } }) };
    await assert.rejects(vm.runInContext("readJson(response)", context), error => error.status === 409
      && error.detail.batch_id === batchId && error.detail.status === "PREVIEW");
    checks += 1;
  }
  console.log("PASS: " + checks + " founder import mapping/rebuild cases, including explicit duplicate recovery, replacement IDs, flags, concurrent clicks, interrupted responses and hidden review rows.");
})().catch(error => { console.error(error); process.exitCode = 1; });
