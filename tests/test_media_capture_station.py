from pathlib import Path


ROOT = Path(__file__).parents[1]
SHOPIFY_SETTINGS = ROOT / "backend" / "app" / "static" / "shopify-settings.js"


def test_media_capture_station_uses_mobile_camera_without_changing_batch_policy() -> None:
    js = SHOPIFY_SETTINGS.read_text()

    assert 'id="shopify-media-file"' in js
    assert 'capture="environment"' in js
    assert 'id="shopify-media-capture-summary"' in js
    assert 'id="shopify-media-previous"' in js
    assert 'id="shopify-media-next"' in js
    assert "function renderMediaCandidateSummary()" in js
    assert "function moveMediaCandidate(offset)" in js

    # Batch safety remains filename/Inventory-ID based and sequential.
    assert "function validateBatchMediaFiles(files)" in js
    assert "parseBatchMediaFilename(file.name)" in js
    assert "for (let index = 0; index < validation.work.length; index += 1)" in js
    assert "await uploadFounderMediaWork(item)" in js


def test_media_navigation_changes_selection_only_and_never_uploads() -> None:
    js = SHOPIFY_SETTINGS.read_text()
    start = js.index("function moveMediaCandidate(offset)")
    end = js.index("function renderShopifyMedia(", start)
    block = js[start:end]

    assert "select.selectedIndex =" in block
    assert 'byId("shopify-media-file")' in block
    assert "file.value = """ in block
    assert "applyMediaCandidateDefaults()" in block
    assert "apiRequest(" not in block
    assert "uploadFounderMedia" not in block
    assert "publish" not in block.casefold()


def test_completed_capture_advances_only_after_a_real_selected_queue_item_disappears() -> None:
    js = SHOPIFY_SETTINGS.read_text()
    start = js.index("function renderMediaIntakeQueue(data)")
    end = js.index("function applyMediaCandidateDefaults()", start)
    block = js[start:end]

    assert "const previous = select.value;" in block
    assert "const previousIndex = select.selectedIndex;" in block
    assert "else if (previous && items.length)" in block
    assert "Math.max(previousIndex, 1)" in block
    assert "applyMediaCandidateDefaults();" in block
