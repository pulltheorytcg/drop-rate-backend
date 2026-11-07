"""Hand-verified official KAYOU Naruto sealed catalogue references.

A small, versioned factual manufacturer manifest; not a website scraper or
market-price feed. Published month is *not* an invented first-of-month date.
No rights to copy publisher packaging images are assumed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

PROVIDER = "Kayou Official"
SYSTEM = "NARUTO_KAYOU"
LANGUAGE = "Unknown"
MODEL = re.compile(r"^NR-[A-Z0-9-]{8,90}$")
PAGE = re.compile(r"^/en-US/series/series-[a-z0-9]{8}$")


@dataclass(frozen=True)
class PublisherProduct:
    product_model: str
    set_name: str
    product_name: str
    product_type: str
    source_url: str
    release_month: str
    packs_per_box: int
    cards_per_pack: int
    product_label: str

    def validate(self) -> None:
        url = urlsplit(self.source_url)
        if (not MODEL.fullmatch(self.product_model)
                or url.scheme != "https" or url.netloc != "www.kayouofficial.com"
                or not PAGE.fullmatch(url.path) or url.query or url.fragment
                or not re.fullmatch(r"20[12][0-9]-(0[1-9]|1[0-2])", self.release_month)
                or self.product_type not in {"BOOSTER_BOX", "COLLECTION"}
                or not 1 <= self.packs_per_box <= 50
                or not 1 <= self.cards_per_pack <= 20
                or not all(1 <= len(t) <= 200 for t in (self.set_name, self.product_name, self.product_label))):
            raise ValueError("Unverified KAYOU product facts")

    def set_record(self) -> dict:
        self.validate()
        return dict(provider=PROVIDER, system_code=SYSTEM, language=LANGUAGE,
                    set_id=self.product_model, name=self.set_name,
                    release_date=None, declared_card_count=None,
                    source_url=self.source_url)

    def product_record(self) -> dict:
        self.validate()
        return dict(provider=PROVIDER, system_code=SYSTEM, language=LANGUAGE,
                    provider_id=self.product_model, set_id=self.product_model,
                    name=self.product_name, product_type=self.product_type,
                    image_url=None, source_url=self.source_url, evidence={
                        "publisher": "Kayou",
                        "published_model": self.product_model,
                        "packaging_label": self.product_label,
                        "packs_per_box": self.packs_per_box,
                        "cards_per_pack": self.cards_per_pack,
                        "release_month": self.release_month,
                        "source_type": "PUBLISHER_PRODUCT_INFORMATION",
                        "publisher_product_reference_verified": True,
                        "physical_language_confirmed": False,
                        "physical_package_verified": False,
                        "physical_valuation_eligible": False,
                        "source_image_rights_verified": False,
                        "market_evidence_status": "UNAVAILABLE",
                        "curation_revision": 1,
                    })


# Each SKU and every numerical pack count were checked on the publisher's
# published product page. Do not deduce any loose-pack SKU from a box.
OFFICIAL_PRODUCTS = (
    PublisherProduct(
        "NR-RDIV-Z001-NA", "Heaven Scroll · Series 1",
        "Naruto Heaven Scroll Series 1 · Version A Booster Box (24 packs)",
        "BOOSTER_BOX",
        "https://www.kayouofficial.com/en-US/series/series-5zdty4vj",
        "2025-09", 24, 8, "Version A",
    ),
    PublisherProduct(
        "NR-KP-DZJ-002A-NA", "Earth Scroll · Series 2",
        "Naruto Earth Scroll Series 2 · Version A Booster Box (20 packs)",
        "BOOSTER_BOX",
        "https://www.kayouofficial.com/en-US/series/series-8idoe481",
        "2026-03", 20, 7, "Version A",
    ),
    PublisherProduct(
        "NR-KP-CC-ZZZ-003A-NA", "Chapter Jin · Series 3",
        "Naruto Chapter Jin Series 3 · Version A Booster Box (12 packs)",
        "BOOSTER_BOX",
        "https://www.kayouofficial.com/en-US/series/series-cv8e3pgi",
        "2026-04", 12, 8, "Version A",
    ),
    PublisherProduct(
        "NR-KP-RZSD-LH-001-NA", "Ninja Age · Premium Collector Box",
        "Naruto Ninja Age · Premium Collector Box (16 packs + promo card)",
        "COLLECTION",
        "https://www.kayouofficial.com/en-US/series/series-0nyket49",
        "2026-08", 16, 5, "Premium Collector Box",
    ),
)


SET_SQL = """insert into tcg.reference_sets
 (provider,system_code,language,set_id,name,release_date,declared_card_count,source_url)
 values($1,$2,$3,$4,$5,$6,$7,$8)
 on conflict(provider,system_code,language,set_id) do update
 set refreshed_at=clock_timestamp()
 where tcg.reference_sets.name=excluded.name
  and tcg.reference_sets.source_url=excluded.source_url
  and tcg.reference_sets.release_date is not distinct from excluded.release_date
 returning set_id"""

PRODUCT_SQL = """insert into tcg.reference_sealed_products
 (provider,system_code,language,provider_id,set_id,name,product_type,image_url,source_url,evidence)
 values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)
 on conflict(provider,system_code,language,provider_id) do update
 set refreshed_at=clock_timestamp()
 where tcg.reference_sealed_products.set_id=excluded.set_id
   and tcg.reference_sealed_products.name=excluded.name
   and tcg.reference_sealed_products.product_type=excluded.product_type
   and tcg.reference_sealed_products.image_url is not distinct from excluded.image_url
   and tcg.reference_sealed_products.source_url=excluded.source_url
   and tcg.reference_sealed_products.evidence=excluded.evidence
 returning provider_id"""


def candidate_manifest() -> list[tuple[dict, dict]]:
    seen = set()
    products = []
    for item in OFFICIAL_PRODUCTS:
        item.validate()
        if item.product_model in seen:
            raise ValueError("Duplicate publisher product model")
        seen.add(item.product_model)
        products.append((item.set_record(), item.product_record()))
    return products


async def register_verified_publisher_products(connection) -> dict:
    """Admin-authorized caller only; no price, physical or Shopify side effects."""
    # Any collision with a changed record fails and rolls back the entire pilot.
    items = candidate_manifest()
    async with connection.transaction():
        for release, product in items:
            set_id = await connection.fetchval(
                SET_SQL, release["provider"], release["system_code"], release["language"],
                release["set_id"], release["name"], release["release_date"],
                release["declared_card_count"], release["source_url"],
            )
            if set_id != release["set_id"]:
                raise ValueError("Existing manufacturer release identity conflict")
            product_id = await connection.fetchval(
                PRODUCT_SQL, product["provider"], product["system_code"],
                product["language"], product["provider_id"], product["set_id"],
                product["name"], product["product_type"], product["image_url"],
                product["source_url"], json.dumps(product["evidence"], sort_keys=True),
            )
            if product_id != product["provider_id"]:
                raise ValueError("Existing manufacturer product identity conflict")
    return {"publisher": PROVIDER, "verified_sealed_references": len(items),
            "market_prices_added": 0, "inventory_items_changed": 0,
            "source_image_rights_verified": False}
