"""Fast Railway-side navigation over fully verified, immutable R2 catalogue inputs.

This handles *shared static counts* in Python and merges only the current
authenticated owner's inventory aggregation from PostgreSQL. It is an
alternative to sending all ~70k R2 references back into a PostgreSQL query.

It does not replace transactional inventory/ownership rules, reference prices,
Shopify decisions or global catalogue search. The legacy SQL remains fallback.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from .recognition_games import SYSTEM_BY_GAME

GAME_BY_SYSTEM = {system: game for game, system in SYSTEM_BY_GAME.items()}
BOOK_SYSTEMS = frozenset(("MARVEL_COMICS", "DC_COMICS", "OTHER_COMICS", "MANGA"))


def _day(value: str | date | None) -> date | None:
    return value if isinstance(value, date) else date.fromisoformat(value) if value else None


def _released(value: str | date | None, today: date) -> bool:
    item = _day(value)
    return item is None or item <= today


def _rkey(row: dict) -> tuple[str, str, str, str]:
    return (row["provider"],row["system_code"],row["language"],row["provider_id"])


@dataclass(slots=True)
class _EntryGroup:
    system_code: str | None
    set_id: str | None
    set_name: str | None
    language: str | None
    provider: str
    game: str | None = None
    release_date: date | None = None
    indexed_count: int = 0
    owners: list[str] = field(default_factory=list)

    def include(self, game: str | None, release: date | None, catalogue_id: str | None):
        self.indexed_count += 1
        if game is not None and (self.game is None or game < self.game):
            self.game = game
        if release is not None and (self.release_date is None or release > self.release_date):
            self.release_date = release
        if catalogue_id is not None:
            self.owners.append(catalogue_id)


@dataclass(frozen=True, slots=True)
class NavigationIndex:
    """Static R2-derived set rows, with per-entry canonical-owner references.

    Each entry carries only a canonical public catalogue ID, not an owner ID,
    current value or authorization decision. Actual per-owner counts are read
    live from PostgreSQL under existing row-level security.
    """

    set_templates: tuple[dict[str, Any], ...]

    def games(self) -> list[dict]:
        summary: dict[str, dict] = {}
        for s in self.set_templates:
            system = s["system_code"]
            if system is None:
                continue
            group = summary.setdefault(system,dict(
                system_code=system,game=None,languages=set(),products=0,sets=0))
            game=s["game"]
            # PostgreSQL's collation orders the friendly "Pokemon" label
            # before the uppercase fallback "POKEMON_TCG" from empty sets.
            # Python's binary comparison does the opposite. Compare the
            # casefolded forms to preserve the intended directory title.
            if game is not None and (group["game"] is None
                                     or game.casefold() < group["game"].casefold()):
                group["game"]=game
            if s["language"] is not None:
                group["languages"].add(s["language"])
            group["products"] += s["indexed_count"]
            group["sets"] += 1
        return [
            {**row,"languages":sorted(row["languages"])}
            for row in sorted(summary.values(),key=lambda g:(
                g["game"] is None,g["game"] or "",g["system_code"]))
        ]

    def sets(
        self, *,
        systems: list[str],
        language: str = "",
        search: str = "",
        limit: int = 41,
        offset: int = 0,
        owner: dict[str, tuple[int, int | None, int]] | None = None,
    ) -> list[dict]:
        if (not isinstance(systems,list) or not systems
                or type(limit) is not int or not 1<=limit<=81
                or type(offset) is not int or not 0<=offset<=100000):
            raise ValueError("Invalid bounded navigation request")
        systems_set=set(systems)
        query=search.lower()
        matches=[]
        for template in self.set_templates:
            if template["system_code"] not in systems_set:
                continue
            if language and template["language"]!=language:
                continue
            if query and query not in (template["set_name"] or "").lower() and query not in (template["set_id"] or "").lower():
                continue
            matches.append(template)
        # PostgreSQL ORDER BY release_date DESC NULLS LAST, set_name, language,
        # provider, set_id. Avoid sorting user data or building a global SQL array.
        matches.sort(key=lambda s:(
            s["release_date"] is None,
            -s["release_date"].toordinal() if s["release_date"] else 0,
            s["set_name"] or "",s["language"] or "",s["provider"] or "",s["set_id"] or ""))
        total=len(matches)
        result=[]
        current=owner or {}
        for row in matches[offset:offset+limit]:
            links=row["_owner_links"]
            owned=sum(1 for k in links if current.get(k,(0,None,0))[0]>0)
            values=[current[k][1] for k in links if k in current and current[k][1] is not None]
            unknown=sum(current[k][2] for k in links if k in current)
            item={k:v for k,v in row.items() if k!="_owner_links"}
            item.update(owned_count=owned,
                        owned_value_minor=sum(values) if values else None,
                        unknown_values=unknown,
                        total_count=total,
                        checklist_status=("UNAVAILABLE" if item["indexed_count"]==0 else
                          "PARTIAL" if item["card_count"]>item["indexed_count"] else "AVAILABLE"))
            result.append(item)
        return result


def build_navigation(
    shared: dict[str, list[dict]],
    *, today: date | None = None,
    verified_mappings: list[dict] | None = None,
) -> NavigationIndex:
    """Reproduce the static GAMES_SQL/SETS_SQL entries, no cross-printing guess.

    A reference links to a canonical card ONLY on all original exact fields
    or an explicitly VERIFIED mapping. An ambiguous multi-canonical reference
    does not link. Unlinked canonicals remain as their own catalogue entries.
    """
    today=today or datetime.now(timezone.utc).date()
    ref_sets={
        (s["provider"],s["system_code"],s["language"],s["set_id"]): s
        for s in shared["reference_sets"] if _released(s["release_date"],today)
    }
    profile={p["catalogue_id"]:p for p in shared["catalogue_product_profiles"]}
    canonical={p["id"]:p for p in shared["catalogue_products"]}
    identity=defaultdict(set)
    for p in shared["catalogue_products"]:
        if p["product_type"]=="CARD":
            identity[(p["game"],p["name"],p["set_name"],p["card_number"],
                      p["language"],p["variant"],p["rarity"])].add(p["id"])

    references=[]
    candidates=defaultdict(set)
    for r in shared["reference_cards"]:
        s=ref_sets.get((r["provider"],r["system_code"],r["language"],r["set_id"]))
        if s is None:
            continue
        references.append((r,s))
        matches=identity.get((
            GAME_BY_SYSTEM.get(r["system_code"],r["system_code"]),
            r["name"],s["name"],r["card_number"],r["language"],r["provider_id"],
            r["rarity"] or "Unknown"),())
        candidates[_rkey(r)].update(matches)
    released_keys={_rkey(r) for r,_ in references}
    for m in verified_mappings or ():
        candidate_key=(
            m["source_provider"],m["system_code"],
            m["provider_language"],m["provider_id"]
        )
        if (candidate_key in released_keys and
                m["provider_entity_type"]=="CARD_PRINTING" and
                m["provider_variant_key"]=="" and
                m["match_status"]=="VERIFIED" and
                m["catalogue_id"] in canonical):
            candidates[candidate_key].add(m["catalogue_id"])

    exact={key:next(iter(ids)) for key,ids in candidates.items() if len(ids)==1}
    linked=set(exact.values())
    groups: dict[tuple, _EntryGroup]={}

    def add(system,set_id,set_name,language,provider,game,release,catalogue_id):
        key=(system,set_id,set_name,language,provider)
        group=groups.get(key)
        if group is None:
            group=_EntryGroup(system,set_id,set_name,language,provider)
            groups[key]=group
        group.include(game,release,catalogue_id)

    for r,s in references:
        add(r["system_code"],r["set_id"],s["name"],r["language"],r["provider"],
            GAME_BY_SYSTEM.get(r["system_code"],r["system_code"]),
            _day(s["release_date"]),exact.get(_rkey(r)))

    for r in shared["reference_sealed_products"]:
        s=ref_sets.get((r["provider"],r["system_code"],r["language"],r["set_id"]))
        if s is not None:
            add(r["system_code"],r["set_id"],s["name"],r["language"],r["provider"],
                GAME_BY_SYSTEM.get(r["system_code"],r["system_code"]),
                _day(s["release_date"]),None)

    for p in shared["catalogue_products"]:
        pr=profile.get(p["id"])
        kind=pr["collectible_type"] if pr else None
        if not (p["product_type"] in ("CARD","SEALED")
                or (p["product_type"]=="COLLECTION" and kind=="SEALED")
                or (p["product_type"]=="COMIC" and kind=="COMIC"
                    and pr and pr["system_code"] in BOOK_SYSTEMS)):
            continue
        if not _released(pr["release_date"] if pr else None,today):
            continue
        if p["id"] in linked:
            continue
        add(pr["system_code"] if pr else None,
            (pr["set_code"] if pr and pr["set_code"] else None) or p["set_name"],
            p["set_name"],p["language"] or "Unknown","",
            p["game"],_day(pr["release_date"]) if pr else None,p["id"])

    by_short=defaultdict(list)
    for g in groups.values():
        by_short[(g.system_code,g.set_id,g.language,g.provider)].append(g)
    output=[]
    for s in ref_sets.values():
        matches=by_short.get((s["system_code"],s["set_id"],s["language"],s["provider"]),())
        for group in matches or (None,):
            indexed=group.indexed_count if group else 0
            output.append(dict(system_code=s["system_code"],set_id=s["set_id"],
                set_name=s["name"],language=s["language"],provider=s["provider"],
                game=(group.game if group and group.game is not None else s["system_code"]),
                release_date=_day(s["release_date"]),indexed_count=indexed,
                card_count=max(s["declared_card_count"] or 0,indexed),
                _owner_links=tuple(group.owners) if group else ()))
    for group in groups.values():
        if group.provider=="":
            output.append(dict(system_code=group.system_code,set_id=group.set_id,
                set_name=group.set_name,language=group.language,provider="",
                game=group.game,release_date=group.release_date,
                indexed_count=group.indexed_count,card_count=group.indexed_count,
                _owner_links=tuple(group.owners)))
    return NavigationIndex(tuple(output))


OWNER_NAVIGATION_SQL = """select catalogue_id,count(*)::int as quantity,
  sum(market_value_minor) as owned_value_minor,
  count(*) filter(where market_value_minor is null)::int as unknown_values
  from tcg.inventory_items
  where owner_id=$1 and status in ('DRAFT','INSPECTION','APPROVED','RESERVED')
  group by catalogue_id"""


async def owned_navigation(connection, owner_id) -> dict[str,tuple[int,int|None,int]]:
    """Retrieve only current authenticated owner-visible transactional aggregates."""
    rows=await connection.fetch(OWNER_NAVIGATION_SQL,owner_id)
    return {str(r["catalogue_id"]):(r["quantity"],r["owned_value_minor"],r["unknown_values"]) for r in rows}
