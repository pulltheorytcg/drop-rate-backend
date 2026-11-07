from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.comic_identity import ComicPrintingCreate
from app.inventory_intake import _manual_identity_key, _manual_intake_payload_hash
from app.schemas import ManualCatalogueCreate, ManualInventoryCreate
from app.physical_state import validate_physical_state


PRINTING = dict(system_code="MARVEL_COMICS", series_title="Amazing Spider-Man", issue_number="1",
                release_year=2022, printing_number=1, cover_code="Cover A")


def product(**changes):
    return ManualCatalogueCreate(product_type="COMIC", game="placeholder", name="placeholder",
        set_name="placeholder", language="English", comic_printing={**PRINTING, **changes})


def test_book_display_and_identity_use_structured_details():
    comic = product()
    assert comic.game == "Marvel Comics" and comic.name == "Amazing Spider-Man #1"
    assert comic.comic_printing.publisher == "Marvel"
    assert _manual_identity_key(comic) == _manual_identity_key(product(series_title="AMAZING SPIDER-MAN"))
    for change in [dict(release_year=2014), dict(printing_number=2), dict(cover_code="Cover B"),
                   dict(volume_identifier="2"), dict(barcode_gtin="1234567890123"), dict(system_code="DC_COMICS")]:
        assert _manual_identity_key(comic) != _manual_identity_key(product(**change))
    translated = comic.model_copy(deep=True); translated.language = "Japanese"
    assert _manual_identity_key(comic) != _manual_identity_key(translated)


def test_manga_requires_publisher_and_keeps_volume_edition_isbn():
    with pytest.raises(ValidationError, match="Publisher"):
        ComicPrintingCreate(system_code="MANGA", series_title="One Piece", issue_number="1", book_format="MANGA")
    comic = product(system_code="MANGA", series_title="One Piece", publisher="VIZ Media",
                    book_format="MANGA", volume_identifier="Omnibus", barcode_gtin="978-1-00000-000-0")
    assert comic.game == "Manga" and comic.name == "One Piece Volume 1"
    assert comic.comic_printing.barcode_gtin == "9781000000000"
    with pytest.raises(ValidationError, match="requires"):
        ComicPrintingCreate(**{**PRINTING, "book_format": "MANGA"})


@pytest.mark.parametrize("condition", ["Mint", "Near Mint", "Very Fine", "Fine", "Very Good", "Good", "Fair", "Poor", None])
def test_raw_books_have_their_own_condition_scale(condition):
    validate_physical_state(product_type="COMIC", condition=condition, seal_status=None, grading_company=None, grade=None)


@pytest.mark.parametrize("grade", ["0.5", "1.8", "9.8", "10"])
def test_graded_books_accept_numeric_book_grades(grade):
    validate_physical_state(product_type="COMIC", condition=None, seal_status=None,
                            grading_company="CBCS", grade=grade, certificate_number="fixture-001")


@pytest.mark.parametrize("change", [dict(condition="Lightly Played"), dict(condition="Near Mint"),
    dict(seal_status="SEALED"), dict(grade="NaN"), dict(grade="Infinity"), dict(grade="1e1"), dict(grade="0"), dict(grade="11")])
def test_invalid_or_mixed_book_state_is_rejected(change):
    with pytest.raises(ValueError):
        validate_physical_state(**{**dict(product_type="COMIC", condition=None, seal_status=None,
            grading_company="CGC", grade="9.8", certificate_number="fixture-001"), **change})


def test_printing_is_part_of_the_intake_receipt_and_grade_is_per_copy():
    first = ManualInventoryCreate(new_catalogue=product(), grading_company="CGC", grade="9.8", certificate_number="A")
    second = first.model_copy(deep=True); second.new_catalogue = product(cover_code="Cover B")
    assert _manual_intake_payload_hash(first) != _manual_intake_payload_hash(second)
    graded = first.model_copy(deep=True); graded.grade = "9.6"; graded.certificate_number = "B"
    assert _manual_identity_key(first.new_catalogue) == _manual_identity_key(graded.new_catalogue)
    assert _manual_intake_payload_hash(first) != _manual_intake_payload_hash(graded)
