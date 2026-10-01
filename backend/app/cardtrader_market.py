from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import UUID

from .cardtrader_client import CardTraderApiError, CardTraderClient
from .cardtrader_recognition import discover_one_piece_cardtrader_sealed_candidates
from .recognition_games import collector_key
from .recognition_vision import RecognitionObservation


_LANGUAGE_CODE = {
    "English": "en",
    "Japanese": "jp",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Spanish": "es",
    "Portuguese": "pt",
    "Korean": "kr",
}


def _language_code(language: str | None) -> str | None:
    return _LANGUAGE_CODE.get(str(language or "").strip())


def _offer_price(row: Mapping[str, Any]) -> tuple[int, str] | None:
    price = row.get("price")
    if not isinstance(price, Mapping):
        return None
    cents = price.get("cents")
    currency = str(price.get("currency") or "").strip().upper()
    if not isinstance(cents, int) or cents <= 0 or len(currency) != 3:
        return None
    return cents, currency


def _offer_language(row: Mapping[str, Any]) -> str | None:
    props = row.get("properties_hash")
    if not isinstance(props, Mapping):
        return None
    for key, value in props.items():
        if "language" not in str(key).casefold():
            continue
        text = str(value or "").strip().casefold()
        if text in {"jp", "ja", "japanese"}:
            return "Japanese"
        if text in {"en", "english"}:
            return "English"
        if text in {"fr", "french"}:
            return "French"
        if text in {"de", "german"}:
            return "German"
        if text in {"it", "italian"}:
            return "Italian"
        if text in {"es", "spanish"}:
            return "Spanish"
        if text in {"pt", "portuguese"}:
            return "Portuguese"
        if text in {"kr", "ko", "korean"}:
            return "Korean"
    return None


def _choose_sealed_candidate(
    observation: RecognitionObservation,
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    observed_code = collector_key(observation.product_code)
    observed_type = str(observation.sealed_product_type or "UNKNOWN").upper()
    viable = [
        row
        for row in rows
        if collector_key(row.get("product_code")) == observed_code
        and str(row.get("sealed_product_type") or "UNKNOWN").upper() == observed_type
        and int(str(row.get("provider_id") or "0")) > 0
    ]
    viable.sort(
        key=lambda row: (
            -float(row.get("retrieval_score") or 0.0),
            str(row.get("provider_id") or ""),
        )
    )
    if not viable:
        return None
    if (
        len(viable) > 1
        and float(viable[0].get("retrieval_score") or 0.0)
        - float(viable[1].get("retrieval_score") or 0.0)
        < 0.05
    ):
        return None
    return viable[0]


async def refresh_cardtrader_sealed_market(
    connection,
    *,
    catalogue_id: UUID,
    observation: RecognitionObservation,
    physical_language: str,
    client: CardTraderClient,
) -> dict[str, Any]:
    """Append current CardTrader sealed listings as market observations.

    This is intentionally conservative: only an unambiguous provider blueprint,
    exact observed set/product code and sealed type, GBP-denominated listings,
    bundle_size=1 and non-vacation listings are accepted.
    """

    provider_rows = await discover_one_piece_cardtrader_sealed_candidates(
        observation,
        client,
    )
    candidate = _choose_sealed_candidate(observation, provider_rows)
    if candidate is None:
        return {
            "status": "UNAVAILABLE",
            "detail": "CardTrader sealed blueprint was ambiguous or unavailable",
            "inserted": 0,
        }

    blueprint_id = int(str(candidate["provider_id"]))
    language_code = _language_code(physical_language)
    offers = await client.list_marketplace_products(
        blueprint_id=blueprint_id,
        language=language_code,
    )

    now = datetime.now(timezone.utc)
    hour_key = now.strftime("%Y%m%d%H")
    accepted: list[dict[str, Any]] = []
    currencies: set[str] = set()

    for row in offers:
        if bool(row.get("on_vacation")):
            continue
        try:
            quantity = int(row.get("quantity") or 0)
            bundle_size = int(row.get("bundle_size") or 1)
        except (TypeError, ValueError):
            continue
        if quantity < 1 or bundle_size != 1 or bool(row.get("graded")):
            continue

        price = _offer_price(row)
        if price is None:
            continue
        price_minor, currency = price
        currencies.add(currency)
        if currency != "GBP":
            continue

        offer_language = _offer_language(row)
        if offer_language and offer_language != physical_language:
            continue

        product_id = row.get("id")
        if not isinstance(product_id, int) or product_id <= 0:
            continue

        user = row.get("user") if isinstance(row.get("user"), Mapping) else {}
        country = str(user.get("country_code") or "").strip().upper()
        if len(country) != 2:
            country = None

        accepted.append(
            {
                "product_id": product_id,
                "price_minor": price_minor,
                "country": country,
                "metadata": {
                    "provider": "CardTrader",
                    "blueprint_id": blueprint_id,
                    "product_id": product_id,
                    "quantity": quantity,
                    "bundle_size": bundle_size,
                    "provider_language": offer_language,
                    "seller_type": user.get("user_type"),
                    "provider_candidate": {
                        "product_code": candidate.get("product_code"),
                        "sealed_product_type": candidate.get("sealed_product_type"),
                        "retrieval_score": candidate.get("retrieval_score"),
                    },
                },
            }
        )

    if not accepted:
        detail = (
            "CardTrader listings are not GBP-denominated"
            if currencies and "GBP" not in currencies
            else "No eligible CardTrader sealed listings were available"
        )
        return {"status": "UNAVAILABLE", "detail": detail, "inserted": 0}

    inserted = 0
    for offer in accepted[:25]:
        status = await connection.execute(
            """
            insert into tcg.market_observations(
                catalogue_id,source,source_record_key,observation_type,observed_at,
                price_minor,shipping_minor,currency,price_gbp_minor,shipping_gbp_minor,
                fx_rate_to_gbp,condition,grading_company,grade,language,seal_status,
                source_country,sample_size,evidence_quality,metadata
            ) values(
                $1,'CARDTRADER',$2,'ACTIVE',$3,
                $4,null,'GBP',$4,null,
                1,null,null,null,$5,'SEALED',
                $6,1,0.72,$7::jsonb
            )
            on conflict (source,source_record_key) do nothing
            """,
            catalogue_id,
            f"sealed-market:{blueprint_id}:{offer['product_id']}:{hour_key}",
            now,
            offer["price_minor"],
            physical_language,
            offer["country"],
            json.dumps(offer["metadata"], default=str),
        )
        if status.endswith("1"):
            inserted += 1

    return {
        "status": "INGESTED" if inserted else "UNCHANGED",
        "inserted": inserted,
        "eligible": len(accepted),
        "blueprint_id": blueprint_id,
    }
