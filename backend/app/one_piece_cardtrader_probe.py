"""Read-only, once-per-process sample of CardTrader's One Piece blueprints.

Owner request (28 Nov 2026): use Cardmarket much more, through exact product
links. One Piece parallels and alternate arts share a collector number with
the base card, so the daily Cardmarket export cannot tell them apart. CardTrader
blueprints carry Cardmarket product IDs. This logs how CardTrader describes
those printings so an exact bridge can be designed from real data.

At most five CardTrader requests, once per worker process. Nothing is written.
"""
import json
import logging

from .cardtrader_client import CardTraderApiError
from .cardtrader_media import _collector_number
from .reference_sealed import normalized as game_name

log = logging.getLogger(__name__)
SAMPLE_CODES = ("OP07", "OP15", "OP01")
_done = False


def blueprint_sample(blueprint):
    return {
        "id": blueprint.get("id"), "name": blueprint.get("name"), "version": blueprint.get("version"),
        "category_id": blueprint.get("category_id"), "collector_number": _collector_number(blueprint),
        "fixed_properties": blueprint.get("fixed_properties"),
        "properties_hash": blueprint.get("properties_hash"),
        "card_market_ids": (blueprint.get("card_market_ids") or [])[:6],
    }


async def probe_once(client):
    """Log a bounded sample. Returns the report, or None if already done."""
    global _done
    if _done:
        return None
    _done = True
    report = {"status": "INCOMPLETE", "provider_calls": 0, "expansions": []}
    try:
        report["provider_calls"] += 1
        games = await client.list_games()
        ids = [g["id"] for g in games if game_name(g.get("name")) in {"one piece", "one piece card game"}]
        if len(ids) != 1:
            raise ValueError("One Piece game identity unavailable")
        report["provider_calls"] += 1
        expansions = [e for e in await client.list_expansions() if e.get("game_id") == ids[0]]
        report["expansion_count"] = len(expansions)
        report["expansion_examples"] = [{"id": e.get("id"), "code": e.get("code"), "name": e.get("name")}
                                        for e in expansions[:40]]
        for code in SAMPLE_CODES:
            chosen = [e for e in expansions if str(e.get("code") or "").upper().replace("-", "") == code]
            if len(chosen) != 1:
                report["expansions"].append({"code": code, "candidates": len(chosen)})
                continue
            report["provider_calls"] += 1
            blueprints = await client.list_blueprints(expansion_id=chosen[0]["id"])
            numbers = {}
            for blueprint in blueprints:
                numbers.setdefault(_collector_number(blueprint), []).append(blueprint)
            shared = [rows for rows in numbers.values() if len(rows) > 1][:4]
            report["expansions"].append({
                "code": code, "expansion": chosen[0].get("name"), "blueprints": len(blueprints),
                "with_cardmarket_ids": sum(bool(b.get("card_market_ids")) for b in blueprints),
                "single_cardmarket_id": sum(len(b.get("card_market_ids") or []) == 1 for b in blueprints),
                "numbers_with_several_printings": sum(len(rows) > 1 for rows in numbers.values()),
                "shared_number_examples": [[blueprint_sample(b) for b in rows[:4]] for rows in shared],
            })
        report["status"] = "COMPLETE"
    except (CardTraderApiError, ValueError, TypeError, KeyError) as exc:
        report.update(status="UNAVAILABLE", reason=type(exc).__name__)
    log.warning("ONE_PIECE_CARDTRADER_PROBE %s", json.dumps(report, default=str)[:60000])
    return report
