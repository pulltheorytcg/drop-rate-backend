"""Factual edition records from Open Library's permitted monthly dumps.

No live bulk API, descriptions, work-level identity, covers or price inference.
"""
from __future__ import annotations
import re
from datetime import date, datetime

DUMP_PATTERN = r"https://archive[.]org/download/ol_dump_(\d{4}-\d{2}-\d{2})/ol_dump_editions_\1[.]txt[.]gz"
LICENSING_URL = "https://openlibrary.org/developers/licensing"
LANGUAGES = {"eng": "English", "jpn": "Japanese", "fre": "French", "fra": "French",
             "ger": "German", "deu": "German", "spa": "Spanish", "ita": "Italian",
             "por": "Portuguese", "kor": "Korean", "chi": "Chinese", "zho": "Chinese"}
# These six English VIZ series already exist in the reviewed local catalogue.
# A country, author nationality or numeric ISBN prefix never classifies manga.
REVIEWED_MANGA_SERIES = frozenset({"one piece", "naruto", "dragon ball z",
    "hunter x hunter", "jujutsu kaisen", "death note"})
VIZ_PUBLISHERS = frozenset({"viz", "viz media", "viz media llc", "viz media, llc",
    "viz communications", "viz communications, inc.", "shonen jump"})


class EditionReviewRequired(ValueError):
    pass


def canonical_isbn(value):
    if not isinstance(value, str):
        raise EditionReviewRequired("ISBN_REQUIRED")
    value = re.sub(r"[-\s]", "", value).upper()
    if re.fullmatch(r"[0-9]{9}[0-9X]", value):
        digits = [int(c) if c != "X" else 10 for c in value]
        if sum(n * (10-i) for i,n in enumerate(digits)) % 11:
            raise EditionReviewRequired("INVALID_ISBN")
        value = "978" + value[:9]
        return value + str((-sum(int(n)*(1 if i%2 == 0 else 3) for i,n in enumerate(value)))%10)
    if (not re.fullmatch(r"97[89][0-9]{10}", value)
            or sum(int(n)*(1 if i%2 == 0 else 3) for i,n in enumerate(value))%10):
        raise EditionReviewRequired("INVALID_ISBN")
    return value


def dump_source(value):
    if not isinstance(value,str) or not re.fullmatch(DUMP_PATTERN,value):
        raise EditionReviewRequired("OFFICIAL_EDITION_DUMP_REQUIRED")
    if date.fromisoformat(re.fullmatch(DUMP_PATTERN,value)[1]) > date.today():
        raise EditionReviewRequired("FUTURE_DUMP")
    return value


def classification_subject(subject):
    return bool(re.search(r"\b(?:manga|comics|comic books|graphic novels?)\b", subject, re.I))


def edition_facts(row):
    edition = row["edition"]
    key = edition.get("key")
    if not isinstance(key,str) or not re.fullmatch(r"/books/OL[1-9][0-9]*M",key):
        raise EditionReviewRequired("EXACT_EDITION_REQUIRED")
    if edition.get("type",{}).get("key") != "/type/edition":
        raise EditionReviewRequired("EXACT_EDITION_REQUIRED")
    publishers = edition.get("publishers")
    if (not isinstance(publishers,list) or len(publishers)!=1
            or not isinstance(publishers[0],str) or not publishers[0].strip()):
        raise EditionReviewRequired("SINGLE_PUBLISHER_REQUIRED")
    publisher = publishers[0].strip()
    langs = edition.get("languages")
    if not isinstance(langs,list) or len(langs)!=1 or not isinstance(langs[0],dict):
        raise EditionReviewRequired("EXPLICIT_LANGUAGE_REQUIRED")
    language = LANGUAGES.get(langs[0].get("key","").removeprefix("/languages/"))
    if not language or not str(langs[0].get("key","")).startswith("/languages/"):
        raise EditionReviewRequired("EXPLICIT_LANGUAGE_REQUIRED")
    isbns = edition.get("isbn_13",[]) + edition.get("isbn_10",[])
    if not isinstance(isbns,list) or not isbns:
        raise EditionReviewRequired("ISBN_REQUIRED")
    normalized = {canonical_isbn(value) for value in isbns}
    if len(normalized)!=1:
        raise EditionReviewRequired("MULTIPLE_EDITION_ISBNS")
    isbn = normalized.pop()
    title = edition.get("title")
    if not isinstance(title,str):
        raise EditionReviewRequired("TITLE_REQUIRED")
    # Preserve all edition/omnibus words; never parse a bare number as a volume.
    match = re.fullmatch(r"(.+?)\s*,?\s+(?:Vol[.]?|Volume|#)\s*([1-9][0-9]*(?:[-–][1-9][0-9]*)?)(?:\s*[:\-]\s*(.+))?", title.strip(),re.I)
    if not match:
        raise EditionReviewRequired("EXPLICIT_ISSUE_OR_VOLUME_REQUIRED")
    series,number = match[1].rstrip(" ,"),match[2]
    if len(series)>140 or len(number)>40 or len(publisher)>100:
        raise EditionReviewRequired("EDITION_FIELD_TOO_LONG")
    if match[3]:
        series += ": " + match[3]
        if len(series)>140:
            raise EditionReviewRequired("EDITION_FIELD_TOO_LONG")
    physical = edition.get("physical_format","")
    if not isinstance(physical,str):
        raise EditionReviewRequired("PHYSICAL_BINDING_REQUIRED")
    binding = {"paperback":"Paperback","hardcover":"Hardcover","hardback":"Hardcover",
               "trade paperback":"Paperback","mass market paperback":"Paperback"}.get(physical.casefold())
    if not binding:
        raise EditionReviewRequired("PHYSICAL_BINDING_REQUIRED")
    subjects = edition.get("subjects",[])
    if not isinstance(subjects,list) or any(not isinstance(s,str) for s in subjects):
        raise EditionReviewRequired("SUBJECT_REVIEW_REQUIRED")
    joined = " | ".join(subjects).casefold()
    manga = bool(re.search(r"\bmanga\b", joined)) or (series.casefold() in REVIEWED_MANGA_SERIES
             and publisher.casefold() in VIZ_PUBLISHERS and language=="English")
    comics = bool(re.search(r"\b(?:comics|comic books|graphic novels?)\b", joined))
    if not manga and not comics:
        raise EditionReviewRequired("COMICS_OR_MANGA_SUBJECT_REQUIRED")
    system = "MANGA" if manga else (
        "MARVEL_COMICS" if publisher.casefold() in {"marvel","marvel comics","marvel enterprises"}
        else "DC_COMICS" if publisher.casefold() in {"dc","dc comics"}
        else "OTHER_COMICS")
    published = edition.get("publish_date")
    if not isinstance(published,str):
        raise EditionReviewRequired("RELEASE_YEAR_REQUIRED")
    years = re.findall(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)",published)
    if len(set(years))!=1:
        raise EditionReviewRequired("RELEASE_YEAR_REQUIRED")
    year = int(years[0])
    if not 1930 <= year < date.today().year:
        raise EditionReviewRequired("RELEASE_YEAR_REVIEW_REQUIRED")
    released = None
    for pattern in ("%Y-%m-%d","%B %d, %Y","%b %d, %Y"):
        try:
            released = datetime.strptime(published,pattern).date().isoformat()
            break
        except ValueError:
            pass
    observed = date.fromisoformat(row["observed_on"])
    if observed>date.today():
        raise EditionReviewRequired("FUTURE_SOURCE_OBSERVATION")
    source = dump_source(row["dump_source"])
    return dict(provider="OPEN_LIBRARY",record_id=key.rsplit("/",1)[-1],
        book=dict(system_code=system,book_format="MANGA" if manga else
            "HARDCOVER" if binding=="Hardcover" else "TRADE_PAPERBACK",
            series_title=series,issue_number=number,publisher=publisher,
            release_year=year,volume_identifier=binding,barcode_gtin=isbn),
        language=language,release_date=released,source_url="https://openlibrary.org"+key,
        observed_on=observed.isoformat(),metadata_license=LICENSING_URL,
        evidence_url=source,image_url=None)


