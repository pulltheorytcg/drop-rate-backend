"""Invented catalogue records for offline tests only; never production seeds."""
from app.book_catalogue_sources import normalise, cover_receipt


def isbn(index):
    base = "9789910" + f"{index:05}"
    return base + str((-sum(int(n) * (1 if i % 2 == 0 else 3) for i, n in enumerate(base))) % 10)


def publisher(index=1, manga=True):
    return dict(record_id=str(index), source_url=f"https://prhcomics.com/book/?isbn={isbn(index)}",
        book=dict(system_code="MANGA" if manga else "OTHER_COMICS", series_title="Fixture Manga" if manga else "Fixture Comic",
                  issue_number=str(index), release_year=2020, publisher="Fixture Publisher",
                  barcode_gtin=isbn(index), book_format="MANGA" if manga else "SINGLE_ISSUE"),
        language="English", release_date="2020-01-02", observed_on="2026-10-21",
        image_url=f"https://images.penguinrandomhouse.com/cover/{isbn(index)}")


def entry(index=1, manga=True, cover=True):
    row = normalise("PUBLISHER", publisher(index, manga))
    if cover:
        row["reference"] = cover_receipt(row, "a" * 64, 300, 450)
    return row


def gcd(index=1, manga=False):
    return dict(issue=dict(api_url=f"https://www.comics.org/api/issue/{index}/", series="https://www.comics.org/api/series/5/",
                           number=str(index), key_date="1999-00-00", on_sale_date=None, isbn="", barcode="",
                           variant_of=None, variant_name="", cover="https://unlicensed.example/cover.jpg"),
        series=dict(api_url="https://www.comics.org/api/series/5/", publisher="https://www.comics.org/api/publisher/9/",
                    name="Fixture GCD Manga" if manga else "Fixture GCD Comic", year_began=1998, language="ja" if manga else "en"),
        publisher=dict(api_url="https://www.comics.org/api/publisher/9/", name="Fixture GCD Publisher"),
        classification=dict(series_id=5, system_code="MANGA" if manga else "OTHER_COMICS", book_format="MANGA" if manga else "SINGLE_ISSUE"),
        observed_on="2026-10-21")


def prh(index=1, manga=True):
    return dict(title=dict(isbn=isbn(index), title="Fixture Omnibus Vol. 1-3" if manga else "Fixture Comics Volume 1",
        subjects=[dict(code="CGN004000" if manga else "CGN000000", description="Comics & Graphic Novels / Manga" if manga else "Comics & Graphic Novels")],
        format=dict(code="TR"), formatFamily="Paperback", consumerImprint="Fixture Publisher", language="E",
        onsale="2020-01-02", seriesNumber=None, version="Regular Edition",
        _links=[dict(rel="icon", href=f"https://images.randomhouse.com/cover/{isbn(index)}")]), observed_on="2026-10-21")


def openlibrary(index=9401,manga=True):
    return dict(edition=dict(key=f"/books/OL{index}M",type={"key":"/type/edition"},
        title=f"Fixture Open Library {'Manga' if manga else 'Comic'} Vol. {index}",
        publishers=["Fixture Publisher"],languages=[{"key":"/languages/eng"}],
        isbn_13=[isbn(index)],physical_format="Paperback",publish_date="January 2, 2020",
        subjects=["Comics & Graphic Novels / Manga" if manga else "Comics"]),
        observed_on="2026-10-26",
        dump_source="https://archive.org/download/ol_dump_2026-09-30/ol_dump_editions_2026-09-30.txt.gz")

