"""Read-only candidate search; retrieval must never approve an identity."""
from __future__ import annotations

import re
import unicodedata


def search_tokens(term: str) -> list[str]:
    """Bounded literal terms can match across number, set and name fields.

    Normalize Unicode, not identity. ALL terms remain required: no silent
    number-only fallback, language default or automatic selection.
    """
    text = unicodedata.normalize("NFKC", term).lower()
    return list(dict.fromkeys(re.findall(r"[^\W_]+", text)))[:64]


CATALOGUE_SEARCH_SQL = """
select p.id,p.game,p.name,p.set_name,p.card_number,
       p.variant,p.language,p.product_type
from tcg.catalogue_products p
where ($2::text = '' or p.product_type = $2)
  and cardinality($3::text[]) > 0
  and not exists (
    select 1 from unnest($3::text[]) as search_term(value)
    where strpos(
      lower(normalize(concat_ws(' ', p.name,p.card_number,p.set_name,
                               p.game,p.variant,p.language), NFKC)),
      search_term.value
    ) = 0
  )
order by
  case when lower(p.card_number)=lower($1) then 0
       when lower(p.name)=lower($1) then 1 else 2 end,
  p.game,p.set_name,p.name,p.card_number,p.id
limit 16
"""
