"""Seller Hub collection import UI uses live secured preview/review routes."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "backend/app/static/owner.html"
CSS = ROOT / "backend/app/static/owner-imports.css"
JS = ROOT / "backend/app/static/owner-imports.js"


def test_inventory_import_menu_has_requested_sources_and_seller_view():
    html = HTML.read_text()
    inventory = html.split('id="owner-view-inventory"', 1)[1].split('id="owner-view-sales"', 1)[0]
    assert 'id="owner-import-trigger"' in inventory
    for adapter in ("COLLECTR", "HOLODEX", "GENERIC_CSV"):
        assert f'data-owner-import-adapter="{adapter}"' in inventory
    assert 'id="owner-import-template"' in html
    assert 'id="owner-import-file"' in html
    assert 'id="owner-import-map-fields"' in html
    assert 'id="owner-import-commit"' in html
    assert 'owner-imports.js?v=1' in html
    assert 'owner-imports.css?v=1' in html
    assert '.csv,.tsv' in html
    assert 'owner-import-template' in JS.read_text()


def test_import_writes_draft_and_does_not_publish_or_leak_owner_data():
    js = JS.read_text()
    assert "/api/v1/owner/imports/preview" in js
    assert "/api/v1/owner/imports/" in js
    assert "/commit" in js
    assert "/candidates/" in js
    assert "/catalogue-search" in js
    assert "loadOwnerInventory" in js
    assert "source_row" in js
    assert "SNAPSHOT_DELTA" in js
    assert "Draft" in js
    assert "innerHTML" not in js
    assert "shopifyProductCreate" not in js
    assert "shipping_address" not in js
    assert "owner_id:" not in js
    assert "auto_publish" not in js


def test_import_dialog_is_lazy_to_preserve_scanner_and_inventory_dialogs():
    js = JS.read_text()
    assert "template.content.firstElementChild.cloneNode(true)" in js
    assert "document.body.append(dialog)" in js
    assert "dialog.showModal()" in js
    assert ".textContent" in js
    assert ".replaceChildren()" in js
    assert 'owner-logout-button' in js
    assert "@media(max-width:660px)" in CSS.read_text()
    assert "#ccff00" not in CSS.read_text().lower()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_import_assets_parse_with_node():
    subprocess.run(["node", "--check", str(JS)], check=True)
    subprocess.run(["node", "--check",
        str(ROOT / "tests/ui/owner-imports.cjs")], check=True)
