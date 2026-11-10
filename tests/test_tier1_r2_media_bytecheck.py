"""Offline tests: R2 image bytes never count until their own SHA + pixels pass."""
from io import BytesIO
from types import SimpleNamespace

from PIL import Image

from scripts.tier1_r2_media_bytecheck import classify_image, summarise


def webp(width=600, height=800):
    out = BytesIO()
    Image.new("RGB", (width, height)).save(out, format="WEBP")
    return out.getvalue()


class StubR2:
    def __init__(self, data=None, head_length=None, fail_read=False):
        self.config = SimpleNamespace(bucket="private-test")
        self.data = data or webp()
        self.fail_read = fail_read
        self.client = SimpleNamespace(head_object=lambda **_: {"ContentLength": head_length if head_length is not None else len(self.data)})

    def read_verified_media(self, key, *, expected_sha256, expected_size):
        if self.fail_read:
            raise ValueError("simulated invalid sha")
        return self.data


def row(**changes):
    defaults = {
        "inventory_code": "INV-TEST-001",
        "game": "Pokemon",
        "language": "English",
        "variant": "Normal",
        "grading_company": None,
        "asset_id": "test-asset",
        "rights_status": "VERIFIED",
        "approval_status": "APPROVED",
        "media_language": "English",
        "media_variant": "Normal",
        "object_key": "drop-rate/private-media/" + "a"*64 + ".webp",
        "content_sha256": "a"*64,
        "size_bytes": len(webp()),
    }
    return defaults | changes


def test_graded_cannot_use_canonical_raw_card():
    assert classify_image(row(grading_company="PSA", asset_id=None), StubR2()) == "NO_APPROVED_SLAB_ASSET"


def test_unapproved_media_cannot_qualify():
    assert classify_image(row(asset_id=None), StubR2()) == "NO_APPROVED_MEDIA_ASSET"
    assert classify_image(row(rights_status="PENDING"), StubR2()) == "MEDIA_RIGHTS_NOT_VERIFIED"


def test_language_and_variant_mismatches_do_not_qualify():
    assert classify_image(row(media_language="Japanese"), StubR2()) == "MEDIA_LANGUAGE_MISMATCH"
    assert classify_image(row(media_variant="Holofoil"), StubR2()) == "MEDIA_VARIANT_MISMATCH"


def test_missing_mirror_cannot_qualify():
    assert classify_image(row(object_key=None), StubR2()) == "NO_R2_MIRROR_RECORD"
    assert classify_image(row(size_bytes=0), StubR2()) == "INVALID_R2_MIRROR_METADATA"


def test_good_webp_is_only_byte_and_dimension_verified():
    assert classify_image(row(), StubR2()) == "R2_BYTES_AND_DIMENSIONS_VERIFIED_VISUAL_UNREVIEWED"


def test_low_resolution_is_explicit_gap():
    assert classify_image(row(), StubR2(data=webp(320, 320))) == "R2_IMAGE_LOW_RESOLUTION"


def test_remote_byte_failure_classified_without_printing_object_key():
    storage = StubR2(fail_read=True, head_length=123)
    assert classify_image(row(), storage) == "R2_SIZE_MISMATCH"


def test_summary_reports_counts_and_bounded_samples_only():
    sample = [row(), row(inventory_code="INV-TEST-002",grading_company="PSA",asset_id=None)]
    report = summarise(sample, StubR2())
    assert report["examined"] == 2
    assert report["status_counts"]["NO_APPROVED_SLAB_ASSET"] == 1
    assert report["status_counts"]["R2_BYTES_AND_DIMENSIONS_VERIFIED_VISUAL_UNREVIEWED"] == 1
    assert not report["full_visual_identity_verified"]
    assert "object_key" not in report["sample_failures"][0]
