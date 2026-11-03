"use strict";
// Physical photographs belong to one owned copy. Reference artwork never enters
// this hand-off, and a failed photo attachment never retries inventory intake.
window.DropRateScanPhotos = (() => {
  const sides = ["FRONT", "BACK", "IDENTIFICATION_ONLY"];
  const storedStates = new Set(["UPLOADED", "PROCESSING", "READY"]);
  const extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"};
  const label = side => ({FRONT: "Front photo", BACK: "Back photo", IDENTIFICATION_ONLY: "Identification only"})[side] || "Photo";

  function create(dataUrl, side = "FRONT") {
    return {dataUrl, side, requestKey: crypto.randomUUID(), asset: null, error: null};
  }

  function sync(photos, previous = []) {
    const used = new Set();
    return photos.map((photo, index) => {
      // Identical image bytes can appear in more than one selected photo. Each
      // occurrence keeps its own side, request key and upload receipt.
      const draft = previous.find(item => item.dataUrl === photo && !used.has(item));
      if (draft) { used.add(draft); return draft; }
      return create(photo, index === 0 ? "FRONT" : "IDENTIFICATION_ONLY");
    });
  }

  function validate(drafts) {
    const used = new Set();
    for (const draft of drafts) {
      if (!sides.includes(draft.side)) throw new Error("Choose how to use each photo.");
      if (draft.side === "IDENTIFICATION_ONLY") continue;
      if (used.has(draft.side)) throw new Error("Choose one photo for each side. Keep extra reference photos for identification only.");
      used.add(draft.side);
      if (!draft.asset && !draft.dataUrl) throw new Error("Choose the photograph again before saving it.");
    }
  }

  function choice(draft, {disabled = false, onChange = () => {}, number = null} = {}) {
    const wrap = document.createElement("label"); wrap.className = "dr-scan-photo-choice";
    const title = document.createElement("span"); title.textContent = number ? `Use photo ${number} as` : "Save scan as";
    const select = document.createElement("select"); select.setAttribute("aria-label", title.textContent);
    for (const side of sides) select.append(new Option(label(side), side));
    select.value = draft.side; select.disabled = disabled || Boolean(draft.asset);
    select.addEventListener("change", () => {
      if (disabled || draft.asset) return;
      draft.side = select.value; draft.requestKey = crypto.randomUUID(); draft.error = null; onChange();
    });
    wrap.append(title, select); return wrap;
  }

  function file(draft) {
    const match = /^data:(image\/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\r\n]+)$/.exec(draft.dataUrl || "");
    if (!match || match[2].length > 16_777_216) throw new Error("Choose a JPG, PNG or WebP photograph up to 12 MB.");
    let decoded;
    try { decoded = atob(match[2]); } catch (_) { throw new Error("This photograph could not be read. Choose it again."); }
    if (!decoded.length || decoded.length > 12 * 1024 * 1024) throw new Error("Choose a photograph up to 12 MB.");
    const bytes = Uint8Array.from(decoded, character => character.charCodeAt(0));
    return {body: new Blob([bytes], {type: match[1]}), type: match[1], filename: `scan-${draft.side.toLowerCase()}.${extension[match[1]]}`};
  }

  function saved(draft) { return Boolean(draft.asset?.id && storedStates.has(draft.asset.shopify_file_status)); }
  function selected(drafts) { return drafts.filter(draft => draft.side !== "IDENTIFICATION_ONLY"); }

  async function attach({request, inventory, drafts, active = () => true}) {
    validate(drafts);
    const check = () => { if (!active()) { const error = new Error("Your account changed. Reopen your collection."); error.name = "AbortError"; throw error; } };
    check();
    const id = inventory?.id || inventory?.inventory_id;
    const chosen = selected(drafts);
    if (!chosen.length) return {complete: true, saved: 0, failed: [], items: []};
    if (!id) throw new Error("The item was saved, but its photo receipt is incomplete. Open the item to add the photo.");
    for (const draft of chosen) {
      if (draft.inventoryId && draft.inventoryId !== id) throw new Error("This photo belongs to another saved copy. Choose its photograph again.");
      draft.inventoryId = id;
    }
    let version = inventory.version;
    const base = `/api/v1/owner/inventory/${encodeURIComponent(id)}`;
    const failed = [];
    for (const draft of chosen) {
      check();
      if (saved(draft)) continue;
      try {
        if (!draft.asset) {
          if (!Number.isInteger(version) || version < 1) {
            const current = await request(base); check(); version = current.item?.version;
            if (!Number.isInteger(version) || version < 1) throw new Error("Refresh this item before retrying the photo.");
          }
          const image = file(draft);
          const query = new URLSearchParams({side: draft.side, version: String(version), filename: image.filename,
            rights_confirmed: "true", request_key: draft.requestKey});
          const result = await request(`${base}/photo/upload?${query}`, {
            method: "POST", headers: {"Content-Type": image.type}, body: image.body,
          });
          check();
          if (!result.asset?.id || result.asset.side !== draft.side) throw new Error("The photo receipt was incomplete. Retry this same photograph.");
          draft.asset = result.asset;
          if (Number.isInteger(result.inventory_version)) version = result.inventory_version;
        }
        // A received upload is resumed, never sent again as a second file.
        if (!saved(draft)) {
          const refreshed = await request(`${base}/photos/refresh`, {method: "POST", body: JSON.stringify({})}); check();
          const asset = refreshed.items?.find(item => item.id === draft.asset.id);
          if (asset) draft.asset = asset;
          if (!saved(draft)) throw new Error(draft.asset.shopify_file_status === "FAILED"
            ? "This photo could not be processed. Open the item to replace it."
            : "Your photo was received but is not ready yet. Retry photo processing.");
        }
        draft.error = null;
      } catch (error) {
        check();
        draft.error = error.message || "Photo upload interrupted. Retry this photo.";
        failed.push({side: draft.side, message: draft.error});
      }
    }
    return {complete: !failed.length, saved: chosen.filter(saved).length, failed,
      items: chosen.map(draft => draft.asset).filter(Boolean)};
  }

  return {create, sync, choice, validate, attach, saved, selected, label};
})();
