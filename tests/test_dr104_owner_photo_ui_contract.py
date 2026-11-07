"""DR104: owner-only physical media must use the authenticated browser image queue.

This is a source-level UI contract; backend unit tests and the live SQL schema
check independently verify ownership, manifest and approval predicates.
"""
from pathlib import Path

JS = (Path(__file__).resolve().parents[1] /
      "backend/app/static/catalogue-browser.js").read_text(encoding="utf-8")


def test_owner_photo_never_becomes_shared_or_public_reference_url():
    assert "row.owner_inventory_image_path" in JS
    assert "const protectedPath=ownerPhotoPath||referencePath;" in JS
    assert "image.src=ownerPhotoPath" not in JS
    assert "urls.push(ownerPhotoPath)" not in JS
    assert "const useReferenceFirst=Boolean(ownerPhotoPath||" in JS
    assert 'this.loadReferenceImage(image,protectedPath,fallback);' in JS
    assert 'const blob=cached && Date.now()-cached.at<3600000?cached.blob:await this.client.requestImage(job.path,{signal:controller.signal});' in JS
    assert "if(urls.length||protectedPath){" in JS
    assert "let exhausted=!(urls.length||protectedPath)" in JS
    assert "approved photo of your own physical copy" in JS


def test_owner_photo_route_is_exact_uuid_and_no_user_supplied_external_url():
    # Only the server-chosen authenticated owned-item route may be fetched.
    assert '/api\\/v1\\/owner\\/inventory\\/[0-9a-f]{8}' in JS
    assert '[0-9a-f]{12}\\/image$/i.test(row.owner_inventory_image_path)' in JS
    assert 'const protectedPath=ownerPhotoPath||referencePath;' in JS
    assert 'this.loadReferenceImage(image,protectedPath,fallback);' in JS
