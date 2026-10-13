"""Strict first-party Cardmarket guides for Masters draft/themed booster releases.

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
NUMBERED_CARD = re.compile(r"((?:DB[123]|TB[123]|EB1)-\d{3})\Z")
MARKET_NUMBER_SUFFIX = re.compile(r"(.+?) \(((?:DB[123]|TB[123]|EB1)-\d{3})\)\Z")
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
    title_map={normalized(entry[1]):set_id for set_id,entry in RELEASES.items()}
    for package in packaging.values():
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
            ref_by_number[(ref["set_id"],ref.get("card_number"))].append(ref)

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

    matched={}
    used=set()
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
        if product["idProduct"] in used:
            continue
        used.add(product["idProduct"])
        matched[(MASTERS,ref["provider_id"])]=product
    return matched


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
