"""Collection intake UI contracts; these are static checks, not live browser proof."""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
HTML=ROOT/'backend/app/static/owner.html'
CSS=ROOT/'backend/app/static/owner-imports.css'
JS=ROOT/'backend/app/static/owner-imports.js'


def test_inventory_import_menu_has_requested_sources_and_seller_view():
    html=HTML.read_text()
    inventory=html.split('id="owner-view-inventory"',1)[1].split('id="owner-view-sales"',1)[0]
    assert 'id="owner-import-trigger"' in inventory
    for adapter in ('COLLECTR','HOLODEX','GENERIC_CSV'):
        assert f'data-owner-import-adapter="{adapter}"' in inventory
    for element in ('owner-import-template','owner-import-file','owner-import-map-fields','owner-import-commit'):
        assert f'id="{element}"' in html
    assert 'owner-imports.js?v=journey-v2' in html
    assert 'owner-imports.css?v=auto-intake-v1' in html
    assert '.csv,.tsv' in html
    assert 'Recognised cards are added to your Draft inventory.' in html
    assert 'owner-import-template' in JS.read_text()


def test_import_writes_draft_without_publication_or_owner_leak():
    js=JS.read_text()
    for route in ('/api/v1/owner/imports/upload','/api/v1/owner/imports/','/commit','/candidates/','/catalogue-search'):
        assert route in js
    for required in ('loadOwnerInventory','source_row','SNAPSHOT_DELTA','Draft','Copies added to inventory','Confirm and add'):
        assert required in js
    for forbidden in ('innerHTML','shopifyProductCreate','shipping_address','owner_id:','auto_publish'):
        assert forbidden not in js
    assert 'state.summary.review_rows === 0 &&' not in js,'Unrelated review rows must not hold recognised copies'
    assert 'state.batch.status = "COMMITTED"' not in js,'The UI must use the server result for partial imports'


def test_import_dialog_remains_lazy_and_escaped():
    js=JS.read_text()
    for required in ('template.content.firstElementChild.cloneNode(true)','document.body.append(dialog)','dialog.showModal()', '.textContent','.replaceChildren()','owner-logout-button'):
        assert required in js
    assert '@media(max-width:660px)' in CSS.read_text()
    assert '#ccff00' not in CSS.read_text().lower()


@pytest.mark.skipif(shutil.which('node') is None,reason='Node.js unavailable')
def test_import_assets_parse_with_node():
    subprocess.run(['node','--check',str(JS)],check=True)
    subprocess.run(['node','--check',str(ROOT/'tests/ui/owner-imports.cjs')],check=True)
