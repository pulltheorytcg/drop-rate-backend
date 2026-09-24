from __future__ import annotations

from typing import Final


KNOWN_BRANDS: Final[tuple[str, ...]] = (
    "One Piece",
    "Pokemon",
    "Dragon Ball",
    "Naruto",
    "Riftbound",
)


def brand_for_game(game: str | None) -> str:
    value = " ".join((game or "").strip().split())
    key = value.casefold()

    if key in {"pokemon", "pokémon"}:
        return "Pokemon"
    if key == "one piece":
        return "One Piece"
    if key.startswith("dragon ball"):
        return "Dragon Ball"
    if key.startswith("naruto"):
        return "Naruto"
    if key.startswith("riftbound"):
        return "Riftbound"
    return value


def brand_sql(alias: str = "p") -> str:
    game = f"{alias}.game"
    return f"""
    case
      when lower(btrim({game})) in ('pokemon', 'pokémon') then 'Pokemon'
      when lower(btrim({game})) = 'one piece' then 'One Piece'
      when lower(btrim({game})) like 'dragon ball%' then 'Dragon Ball'
      when lower(btrim({game})) like 'naruto%' then 'Naruto'
      when lower(btrim({game})) like 'riftbound%' then 'Riftbound'
      else btrim({game})
    end
    """.strip()
