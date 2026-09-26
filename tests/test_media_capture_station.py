from pathlib import Path


ROOT = Path(__file__).parents[1]
SHOPIFY_SETTINGS = ROOT / "backend" / "app" / "static" / "shopify-settings.js"
MEDIA_CONDITION = ROOT / "backend" / "app" / "static" / "media-condition.js"


def test_media_capture_station_uses_mobile_camera_without_changing_batch_policy() -> None:
    helper = SHOPIFY_SETTINGS.read_text()
    ui = MEDIA_CONDITION.read_text()

    assert 'id="shopify-media-file"' in ui
    assert 'capture="environment"' in ui
    assert 'id="shopify-media-capture-summary"' in ui
    assert 'id="shopify-media-previous"' in ui
    assert 'id="shopify-media-next"' in ui
    assert 'id="shopify-media-context"' in ui
    assert "function renderMediaCandidateSummary()" in helper
    assert "function moveMediaCandidate(offset)" in helper

    # Batch safety remains filename/Inventory-ID based and sequential.
    assert "function validateBatchMediaFiles(files)" in helper
    assert "parseBatchMediaFilename(file.name)" in helper
    assert "for (let index = 0; index < validation.work.length; index += 1)" in helper
    assert "await uploadFounderMediaWork({...item, captureContext: item.captureContext})" in helper


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
