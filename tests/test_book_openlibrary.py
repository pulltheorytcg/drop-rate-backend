import gzip
import io
import json
from copy import deepcopy
import pytest
from app.book_openlibrary import canonical_isbn, edition_facts, EditionReviewRequired
from scripts.select_openlibrary_books import select_dump, redirect_allowed

DUMP = "https://archive.org/download/ol_dump_2026-09-30/ol_dump_editions_2026-09-30.txt.gz"


def sample(index=1):
    base = "9789910" + f"{index:05}"
    isbn = base + str((-sum(int(n)*(1 if i%2==0 else 3) for i,n in enumerate(base)))%10)
    return dict(edition=dict(key=f"/books/OL{index}M",type={"key":"/type/edition"},
        title=f"Fixture Manga Vol. {index}",publishers=["Fixture Publisher"],
        languages=[{"key":"/languages/eng"}],isbn_13=[isbn],physical_format="Paperback",
        publish_date="January 2, 2020",subjects=["Comics & Graphic Novels / Manga"],
        covers=[123],description="Must never enter the catalogue snapshot"),
        observed_on="2026-10-26",dump_source=DUMP)


def dump(*samples):
    return io.BytesIO(gzip.compress("".join("/type/edition\t"+r["edition"]["key"]+
        "\t1\t2026-09-01T00:00:00Z\t"+json.dumps(r["edition"])+"\n" for r in samples).encode()))


def test_exact_physical_edition_has_provenance_but_no_cover_price_or_printing():
    facts = edition_facts(sample())
    assert facts["provider"]=="OPEN_LIBRARY"
    assert facts["book"]["volume_identifier"]=="Paperback"
    assert facts["book"]["system_code"]=="MANGA"
    assert facts["book"]["issue_number"]=="1"
    assert facts["book"].get("printing_number") is None
    assert facts["image_url"] is None
    assert facts["metadata_license"]=="https://openlibrary.org/developers/licensing"
    assert facts["evidence_url"]==DUMP


@pytest.mark.parametrize("field,value,reason",[
    ("key","/works/OL1W","EXACT_EDITION_REQUIRED"),
    ("publishers",["One","Two"],"SINGLE_PUBLISHER_REQUIRED"),
    ("languages",[],"EXPLICIT_LANGUAGE_REQUIRED"),
    ("languages",[{"key":"/languages/eng"},{"key":"/languages/jpn"}],"EXPLICIT_LANGUAGE_REQUIRED"),
    ("isbn_13",["9789910000011"],"INVALID_ISBN"),
    ("physical_format","Ebook","PHYSICAL_BINDING_REQUIRED"),
    ("title","Fixture Manga 1","EXPLICIT_ISSUE_OR_VOLUME_REQUIRED"),
    ("title","86","EXPLICIT_ISSUE_OR_VOLUME_REQUIRED"),
    ("subjects",["Japan","Fiction"],"COMICS_OR_MANGA_SUBJECT_REQUIRED"),
    ("publish_date","2020 or 2021","RELEASE_YEAR_REQUIRED"),
    ("publish_date","2027","RELEASE_YEAR_REVIEW_REQUIRED"),
])
def test_ambiguous_source_facts_are_reviewed(field,value,reason):
    row=sample(); row["edition"][field]=value
    with pytest.raises(EditionReviewRequired,match=reason):
        edition_facts(row)


def test_manga_requires_explicit_subject_or_existing_reviewed_series_and_publisher():
    row=sample(); row["edition"].update(title="One Piece Vol. 7",publishers=["VIZ Media LLC"],subjects=[])
    assert edition_facts(row)["book"]["system_code"]=="MANGA"
    row["edition"]["publishers"]=["Another Publisher"]
    with pytest.raises(EditionReviewRequired):
        edition_facts(row)


def test_aliases_normalize_without_inventing_printing():
    assert canonical_isbn("1-59116-852-X")=="9781591168522"
    row=sample();row["edition"]["isbn_10"]=["159116852X"];row["edition"]["isbn_13"]=["9781591168522"]
    assert edition_facts(row)["book"]["barcode_gtin"]=="9781591168522"
    row["edition"]["isbn_13"].append("9781421500751")
    with pytest.raises(EditionReviewRequired,match="MULTIPLE"):
        edition_facts(row)


def test_pilot_is_bounded_and_removes_non_factual_payloads():
    data,report=select_dump(dump(sample(1),sample(2),sample(3)),DUMP,
        observed_on="2026-10-26",max_rows=2)
    rows=[json.loads(line) for line in data.splitlines()]
    assert len(rows)==report["accepted_records"]==2
    assert report["stop_reason"]=="ACCEPTED_ROW_LIMIT"
    assert report["complete_dump_read"] is False
    assert all("covers" not in r["edition"] and "description" not in r["edition"] for r in rows)
    assert all(edition_facts(r)["image_url"] is None for r in rows)


def test_conflicting_isbn_removes_both_candidates():
    one=sample(1); two=sample(2)
    two["edition"]["isbn_13"]=one["edition"]["isbn_13"]
    data,report=select_dump(dump(one,two),DUMP,observed_on="2026-10-26")
    assert data==b""
    assert report["accepted_records"]==0 and report["rejected_records"]==2
    assert report["rejection_reasons"]["CONFLICTING_EDITION_ISBN"]==2


def test_unchanged_duplicate_isbn_deduplicates_different_source_ids():
    one=sample(1); two=deepcopy(one);two["edition"]["key"]="/books/OL2M"
    data,report=select_dump(dump(one,two),DUMP,observed_on="2026-10-26")
    assert report["accepted_records"]==1 and report["rejected_records"]==1


def test_raw_and_compressed_limits_never_claim_complete_dump():
    data,report=select_dump(dump(sample(1)),DUMP,max_raw_bytes=10,observed_on="2026-10-26")
    assert not data and report["stop_reason"]=="RAW_BYTE_LIMIT" and report["raw_bytes_read"]<=10
    data,report=select_dump(dump(sample(1)),DUMP,max_bytes=20,observed_on="2026-10-26")
    assert not data and report["stop_reason"]=="COMPRESSED_BYTE_LIMIT"
    assert report["compressed_bytes_read"]==20


@pytest.mark.parametrize("url",["http://archive.org/a","https://archive.org.attacker.test/a",
    "https://user:pass@archive.org/a","https://127.0.0.1/a"])
def test_redirects_cannot_leave_official_archive_hosts(url):
    assert not redirect_allowed(url)


def test_bulk_api_is_not_an_input():
    with pytest.raises(EditionReviewRequired):
        select_dump(dump(sample()),"https://openlibrary.org/search.json?q=manga")




def test_conflicting_source_id_quarantines_both_isbns():
    one=sample(1);two=sample(2);two["edition"]["key"]=one["edition"]["key"]
    data,report=select_dump(dump(one,two),DUMP,observed_on="2026-10-26")
    assert data==b""
    assert report["rejected_records"]==report["scanned_records"]==2
    assert report["rejection_reasons"]["CONFLICTING_SOURCE_RECORD"]==2


def test_long_classification_subject_cannot_create_an_invalid_snapshot():
    row=sample();row["edition"]["subjects"]=["Manga "+("x"*250)]
    data,report=select_dump(dump(row),DUMP,observed_on="2026-10-26")
    assert not data and report["accepted_records"]==0
    assert report["rejected_records"]==1


def test_manganese_is_not_manga():
    row=sample();row["edition"]["subjects"]=["Manganese chemistry"]
    with pytest.raises(EditionReviewRequired,match="COMICS_OR_MANGA_SUBJECT_REQUIRED"):
        edition_facts(row)
