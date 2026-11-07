"""Strict first-party Cardmarket guides for Masters supplemental releases.

These English Bandai checklist families previously had no price matches because
their official release titles are not the general "Booster -NAME-" format.
Never infer a market product from a collector number alone, price availability,
release order, or other cards owned by a seller. All prices remain *guides*.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .one_piece_market import normalized
from .dragon_ball_market import MASTERS

PROVIDER = "Bandai Official"
SOURCE_CATEGORY = "Dragon Ball Super Singles"
# Each exact official release title has a separately published English
# Cardmarket named booster/set/box. Unknown titles and all promo releases fail.
RELEASES = {
    "428601": ("DRAFT BOX 04 -DRAGON BRAWL-", "Dragon Brawl", "DB1"),
    "428602": ("DRAFT BOX 05 -Divine Multiverse-", "Divine Multiverse", "DB2"),
    "428603": ("DRAFT BOX 06 -Giant Force-", "Giant Force", "DB3"),
    "428101": ("Themed Booster -The Tournament Of Power-", "The Tournament of Power", "TB1"),
    "428102": ("Themed Booster -World Martial Arts Tournament-", "World Martial Arts Tournament", "TB2"),
    "428103": ("Themed Booster -CLASH OF FATES-", "Clash of Fates", "TB3"),
    "428201": ("Battle Evolution Booster", "Battle Evolution Booster", "EB1"),
}
# Exact publisher titles, packaging labels and printed number families from
# the official checklist and Cardmarket export. Packaging versions corroborate
# a release only; they never identify a card's parallel artwork or finish.
EXPANSION_RELEASES = {
    "428401": ("EXPANSION DECK BOX SET 01 -Mighty Heroes-", "Expansion Set: Mighty Heroes", "EX01"),
    "428402": ("EXPANSION DECK BOX SET 02 -Dark Demon’s Villains-", "Expansion Set: Dark Demon's Villains", "EX02"),
    "428403": ("ULTIMATE BOX", "Expansion Set: Ultimate Box", "EX03"),
    "428404": ("EXPANSION SET 04 -Unity of Saiyans-", "Expansion Set: Unity of Saiyans", "EX04"),
    "428405": ("EXPANSION SET 05 -Unity of Destruction-", "Expansion Set: Unity of Destruction", "EX05"),
    "428406": ("Special Anniversary Box", "Expansion Set: Special Anniversary Box", "EX06"),
    "428407": ("EXPANSION SET Magnificent Collection -Fusion Hero-", "Magnificent Collection Fusion Hero", "EX07"),
    "428408": ("EXPANSION SET Magnificent Collection -Forsaken Warrior-", "Magnificent Collection Forsaken Warrior", "EX08"),
    "428409": ("EXPANSION SET 09 -Saiyan Surge-", "Expansion Set: Saiyan Surge", "EX09"),
    "428410": ("EXPANSION SET 10 -Namekian Surge-", "Expansion Set: Namekian Surge", "EX10"),
    "428411": ("EXPANSION SET 11 -Universe 7 Unison-", "Expansion Set: Universe 7 Unison", "EX11"),
    "428412": ("EXPANSION SET 12 -Universe 11 Unison-", "Expansion Set: Universe 11 Unison", "EX12"),
    "428413": ("Special Anniversary Box 2020", "Expansion Set: Special Anniversary Box 2020", "EX13"),
    "428414": ("EXPANSION SET 14 -Battle Advanced-", "Expansion Set: Battle Advanced", "EX14"),
    "428415": ("EXPANSION SET 15 -Battle Enhanced-", "Expansion Set: Battle Enhanced", "EX15"),
    "428416": ("Ultimate Deck", "Expansion Set: Ultimate Deck", "EX16"),
    "428417": ("EXPANSION SET 17 -Saiyan Boost-", "Expansion Set: Saiyan Boost", "EX17"),
    "428418": ("EXPANSION SET 18 -Namekian Boost-", "Expansion Set: Namekian Boost", "EX18"),
    "428419": ("Special Anniversary Box 2021", "Expansion Set: Special Anniversary Box 2021", "EX19"),
    "428420": ("Ultimate Deck 2022", "Expansion Set: Ultimate Deck 2022", "EX20"),
    "428421": ("5th Anniversary Set", "Expansion Set: 5th Anniversary Set", "EX21"),
    "428422": ("Ultimate Deck 2023", "Expansion Set: Ultimate Deck 2023", "EX22"),
    "428423": ("Premium Anniversary Box 2023", "Premium Anniversary Box 2023", "EX23"),
    "428424": ("Premium Anniversary Box 2024", "Premium 7th Anniversary Box 2024", "EX24"),
    "428425": ("Premium Anniversary Box 2025", "Premium Anniversary Box 2025", "EX25"),
    "428501": ("EXPERT DECK -UNIVERSE 6 ASSAILANTS-", "Expert Deck: Universe 6 Assailants", "XD1"),
    "428502": ("EXPERT DECK -ANDROID DUALITY-", "Expert Deck: Android Duality", "XD2"),
    "428503": ("EXPERT DECK -THE ULTIMATE LIFE FORM-", "Expert Deck: The Ultimate Life Form", "XD3"),
}
RELEASES.update(EXPANSION_RELEASES)
EXPANSION_BASIS = "EXACT_MASTERS_EXPANSION_RELEASE_UNIQUE_PRINTING"
NUMBER_PATTERN = r"(?:(?:DB[123]|TB[123])-\d{3}|(?:EB1|EX\d{2}|XD[123])-\d{2})"
NUMBERED_CARD = re.compile(NUMBER_PATTERN+r"\Z")
MARKET_NUMBER_SUFFIX = re.compile(r"(.+?) \(("+NUMBER_PATTERN+r")\)\Z")
SET_LABEL = re.compile(
    r"(.+): (?:Common|Uncommon|Rare|Super Rare|Special Rare|Secret Rare|"
    r"Feature Rare|Full) Set\Z",
    re.I,
)
CATEGORY_IDS = {
    ("Dragon Ball Super Boosters", 1050),
    ("Dragon Ball Super Booster Boxes", 1052),
    ("DBS Set", 1051),
    ("Dragon Ball Super Draft Boxes", 1055),
}
RELEASE_BASIS = "EXACT_BANDAI_MASTERS_DRAFT_THEMED_RELEASE_UNIQUE_NAME_AND_MARKET_EXPANSION"


def _release_expansion_ids(packaging: dict) -> dict[str, int]:
    """Find unique corroborated expansions from real release product labels.

    Do NOT use collector/pre-release/reprint/Power Booster packs as proof of
    base-set expansion. Product category and ID must agree; conflicting IDs
    invalidate the release rather than picking a priced one.
    """
    ids: dict[str, set[int]] = defaultdict(set)
    title_map={normalized(entry[1]):set_id for set_id,entry in RELEASES.items()
               if set_id not in EXPANSION_RELEASES}
    packages = {}
    for set_id, (_, title, prefix) in EXPANSION_RELEASES.items():
        category = ("Dragon Ball Super Starter Decks", 1053) if prefix.startswith("XD") else (
            "Dragon Ball Super Expansion Sets", 1061)
        titles = [title]
        if set_id in {"428406", "428413", "428419"}:
            titles += [title+f" (Version {version})" for version in range(1, 5)]
        for label in titles:
            packages[(*category, normalized(label))] = set_id
    for package in packaging.values():
        set_id = packages.get((package.get("categoryName"), package.get("idCategory"),
                               normalized(package.get("name") or "")))
        expansion = package.get("idExpansion")
        if set_id and type(expansion) is int and expansion > 0:
            ids[set_id].add(expansion)
        if (package.get("categoryName"),package.get("idCategory")) not in CATEGORY_IDS:
            continue
        title=str(package.get("name") or "")
        head=None
        if package["idCategory"]==1051:
            match=SET_LABEL.fullmatch(title)
            if match:head=match[1]
        elif package["idCategory"] in {1050,1052}:
            suffix=" Booster Box" if package["idCategory"]==1052 else " Booster"
            if title.endswith(suffix):
                head=title[:-len(suffix)]
        elif package["idCategory"]==1055:
            match=re.fullmatch(r"Draft Box (?:04|05|06): (.+)",title,re.I)
            if match:head=match[1]
        if head is None:
            continue
        set_id=title_map.get(normalized(head))
        expansion=package.get("idExpansion")
        if set_id and type(expansion) is int and expansion>0:
            ids[set_id].add(expansion)
    return {set_id:next(iter(values)) for set_id,values in ids.items() if len(values)==1}


def exact_masters_supplemental_matches(references: list[dict],singles: dict,packaging: dict) -> dict:
    """(system, provider_id) -> unique matching source product, or no match."""
    expansions=_release_expansion_ids(packaging)
    # Count ALL publisher variants, including parallel and promo suffixes:
    # if the same identity/name has another official printing, no base guide.
    ref_by_name: dict[tuple[str,str],list[dict]]=defaultdict(list)
    ref_by_number: dict[tuple[str,str],list[dict]]=defaultdict(list)
    for ref in references:
        identity=RELEASES.get(str(ref.get("set_id") or ""))
        if (
            identity and ref.get("provider")==PROVIDER
            and ref.get("language")=="English" and ref.get("system_code")==MASTERS
            and ref.get("set_name")==identity[0]
        ):
            ref_by_name[(ref["set_id"],normalized(ref.get("name") or ""))].append(ref)
            number = ref.get("card_number")
            if ref["set_id"] in EXPANSION_RELEASES and isinstance(number, str):
                number = number.split("_", 1)[0]
            ref_by_number[(ref["set_id"],number)].append(ref)

    products:dict[tuple[int,str],list[tuple[dict,str|None]]]=defaultdict(list)
    for p in singles.values():
        if (
            p.get("categoryName") != SOURCE_CATEGORY or p.get("idCategory")!=1049
            or type(p.get("idProduct")) is not int or p["idProduct"]<=0
            or type(p.get("idExpansion")) is not int or p["idExpansion"]<=0
        ):
            continue
        label=str(p.get("name") or "")
        suffix=MARKET_NUMBER_SUFFIX.fullmatch(label)
        name=suffix[1] if suffix else label
        number=suffix[2] if suffix else None
        key=(p["idExpansion"],normalized(name))
        if key[1]:
            products[key].append((p,number))

    possible={}
    product_claims=defaultdict(list)
    for (set_id,name),refs in ref_by_name.items():
        if len(refs)!=1 or not name:
            continue
        ref=refs[0]
        number=ref.get("card_number")
        expected=RELEASES[set_id]
        if (
            len(ref_by_number[(set_id,number)]) != 1
            or not isinstance(number,str) or NUMBERED_CARD.fullmatch(number) is None
            or not number.startswith(expected[2]+"-")
            or ref.get("provider_id")!=set_id+":"+number+".png"
        ):
            continue
        expansion=expansions.get(set_id)
        if expansion is None:
            continue
        candidates=products.get((expansion,name),[])
        # The public product list may contain two unpriced/alternative items:
        # never resolve the ambiguity using guide price, array order or stock.
        if len(candidates)!=1:
            continue
        product,market_number=candidates[0]
        if market_number is not None and market_number!=number:
            continue
        key=(MASTERS,ref["provider_id"])
        possible[key]=product
        product_claims[product["idProduct"]].append(key)
    # If one Cardmarket SKU claims two different publisher cards, reject
    # *both*. Iteration/query order must never determine which card gets priced.
    return {
        key:product for key,product in possible.items()
        if len(product_claims[product["idProduct"]])==1
    }


def supplemental_coverage(references:list[dict],matched:dict,prices:dict)->dict:
    by_release={}
    for set_id,(official,_,_) in RELEASES.items():
        refs=[r for r in references if r.get("set_id")==set_id and
              r.get("system_code")==MASTERS and r.get("language")=="English"]
        chosen=[matched[(MASTERS,r["provider_id"])] for r in refs
                if (MASTERS,r["provider_id"]) in matched]
        guides=sum(
            prices.get(str(p["idProduct"]),{}).get("idCategory")==1049 and
            isinstance(prices.get(str(p["idProduct"]),{}).get("trend"),(int,float)) and
            prices[str(p["idProduct"])]["trend"]>0
            for p in chosen
        )
        by_release[set_id]={"checked":len(refs),"matched":len(chosen),"positive_trend_present":guides}
    return by_release
