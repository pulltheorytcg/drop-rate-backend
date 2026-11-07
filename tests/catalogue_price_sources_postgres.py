"""Execute the actual catalogue price projection in disposable PostgreSQL."""
import asyncio
import json
import os
from datetime import datetime, timezone

import asyncpg
from app.catalogue_browser import price_columns


async def main():
    conn = await asyncpg.connect(os.environ["POKEMON_ARTWORK_TEST_DSN"])
    try:
        sql = "select " + price_columns("e") + """
          from (select 'REFERENCE'::text source_kind,425::bigint reference_value_minor,
            500::bigint reference_value_high_minor,$2::timestamptz reference_pricing_updated_at,
            $1::jsonb market_quotes) e
          cross join (select $3::bigint market_value_minor,
            case when $3::bigint is not null then 'Near Mint'::text end as basis_condition,$4::timestamptz pricing_updated_at,
            'STORED_SNAPSHOT'::text valuation_source) v"""
        stamp = datetime(2026,10,20,tzinfo=timezone.utc)
        cases = [
            ("POKEWALLET_POKEMON_CARDMARKET_CATALOGUE", None, "mixed-language guide"),
            ("POKEWALLET_POKEMON_CARDMARKET_CATALOGUE", "MIXED_NON_ENGLISH_REFERENCE", "Japanese language not verified"),
            ("CARDMARKET_CATALOGUE", None, "mixed-language guide"),
            ("CARDMARKET_BULK_SINGLES", None, "mixed-language guide"),
            ("TCGDEX_CARDMARKET_VARIANT", None, "Raw · Cardmarket"),
        ]
        for source, role, basis in cases:
            quote = {"source":source, "price_gbp_minor":425}
            if role: quote["valuation_role"] = role
            row = await conn.fetchrow(sql,json.dumps([quote]),stamp,None,None)
            assert row["market_value_minor"] == 425 and row["market_value_high_minor"] == 500
            assert row["market_value_source"] == source, dict(row)
            assert basis in row["basis_condition"], dict(row)
            assert row["pricing_updated_at"] == stamp
            sold = await conn.fetchrow(sql,json.dumps([quote]),stamp,999,stamp)
            assert sold["market_value_minor"] == 999
            assert sold["market_value_source"] == "STORED_SNAPSHOT"
            assert sold["basis_condition"] == "Near Mint"
        print("PASS: actual catalogue SQL retains guide source, regional limits, dates and stored-sold precedence")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
