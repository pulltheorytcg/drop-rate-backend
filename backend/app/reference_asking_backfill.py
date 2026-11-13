"""Explicit, resumable official-Browse backfill of separate asking estimates.

No scheduler, inventory/store writes, retry loop, seller names or raw responses.
Each Browse reservation and cursor commit precedes HTTP; uncertain attempts are
skipped on resume. Price history and its cache replacement share one transaction.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
import time
from uuid import UUID, uuid4

import httpx

from .access_control import require_platform_admin
from .database_capacity import check_database_capacity
from .ebay_official_client import EbayApiError
from .reference_applicability import DIGITAL_REFERENCE_SQL
from .reference_asking_funnel import begin_funnel, record_estimate
from .reference_multi_query_search import (
    EARLY_STOP_PLAUSIBLE, MAX_CANDIDATE_SUMMARIES, MAX_DETAILS_PER_REFERENCE,
    build_reference_search_plan,
)
from .reference_asking_display import asking_cache_join, matching_reference_evidence, reference_number_alias as _number_alias
from .reference_asking_estimator import (
    _GRADE_RE, _MULTI_RE, _aspects, _number_matches, _text,
    _LANGUAGES, _SET_CODES, _SPECIAL_MARKERS, _condition_matches,
    _explicitly_denies, _listing_finish, _matches, _phrase, _reference_spec,
    _variant_markers,
    estimate_reference_asking_price, reference_asking_eligibility,
)

KEYS = ("provider", "system_code", "language", "provider_id")
IDENTITY = ("name", "set_id", "card_number", "set_name", "finish", "rarity")
CONTEXT = "CONFIGURED_SHOP_POSTCODE_BENCHMARK"
MAX_DAILY = 2000
HEADROOM = 500
MAX_SCAN = 20000
QUOTA_REFRESH_REQUESTS = 100
MAX_ITEM_DETAILS_PER_CARD = 6
MAX_TARGET_REFERENCES = 25
MAX_RUN_SECONDS = 45 * 60
LOCK_NAME = "tcg.reference_asking_backfill"
GAMES = {"POKEMON_TCG": "Pokemon", "ONE_PIECE_CARD_GAME": "One Piece",
         "DRAGON_BALL_SUPER_FUSION_WORLD": "Fusion World",
         "DRAGON_BALL_SUPER_MASTERS": "Dragon Ball Super",
         "NARUTO_BANDAI_LEGACY": "Naruto Bandai", "NARUTO_KAYOU": "Naruto Kayou"}

# These p/b joins preserve the current catalogue coverage identity guards. A
# stale row's existence is not evidence, and an available guide must not be
# replaced merely because the primary market-price row is missing.
FROM_SQL = f"""from tcg.reference_cards r
join tcg.reference_sets s using(provider,system_code,language,set_id)
left join tcg.reference_market_prices p
 on (p.provider,p.system_code,p.language,p.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
 and (coalesce(p.quotes->0->>'match_basis','')<>'CARDTRADER_MASTERS_NUMBER_RARITY_SINGLETON_CARDMARKET_ID'
      or r.rarity is not distinct from p.quotes->0->>'reference_rarity')
 and (coalesce(p.quotes->0->>'source','')<>'CARDMARKET_BULK_SINGLES'
      or p.quotes->0->'reference_identity'=jsonb_build_object(
       'name',r.name,'set_id',r.set_id,'card_number',r.card_number,'set_name',s.name))
left join tcg.reference_catalogue_prices b
 on (b.provider,b.system_code,b.language,b.provider_id)=(r.provider,r.system_code,r.language,r.provider_id)
 and b.pricing_updated_at>=now()-interval '7 days'
 and b.quotes->0->'reference_identity'=jsonb_build_object(
  'name',r.name,'set_id',r.set_id,'card_number',r.card_number,'set_name',s.name)
{asking_cache_join()}
"""
NEEDS_PRICE = """not (coalesce(p.market_value_minor>0 and p.pricing_updated_at>=now()-interval '7 days',false)
 or coalesce(b.market_value_minor>0,false) or a.provider_id is not null)"""


GROUP_COUNT = f"""(select count(*)::integer from tcg.reference_cards other
 where (other.provider,other.system_code,other.language,other.set_id)=
       (r.provider,r.system_code,r.language,r.set_id)
 and {_number_alias('other')}={_number_alias('r')}) as reference_group_count"""
SELECT_SQL = f"select r.*,s.name as set_name,{GROUP_COUNT},({NEEDS_PRICE}) as needs_price, (a.provider_id is not null) as has_current_asking\n{FROM_SQL}"
CANDIDATES_SQL = SELECT_SQL + f"""where not ({DIGITAL_REFERENCE_SQL}) and r.language<>'Unknown'
 and (({NEEDS_PRICE}) or ($8::boolean and a.provider_id is null))
 and (r.provider,r.system_code,r.language,r.provider_id)>($1,$2,$3,$4)
 and ($6::text is null or r.system_code=$6) and ($7::text is null or r.language=$7)
 and ($9::jsonb is null or exists (
   select 1 from jsonb_array_elements($9::jsonb) target_key
   where (r.provider,r.system_code,r.language,r.provider_id)=
         (target_key->>0,target_key->>1,target_key->>2,target_key->>3)))
 order by r.provider,r.system_code,r.language,r.provider_id limit $5"""
CURRENT_SQL = SELECT_SQL + """where (r.provider,r.system_code,r.language,r.provider_id)=($1,$2,$3,$4)
 for update of r"""
SNAPSHOT_COLUMNS = ("provider", "system_code", "language", "provider_id", "snapshot_id", "reference_identity",
                    "estimate_minor", "estimate_high_minor", "currency", "listing_count", "seller_count",
                    "observed_at", "checked_at", "expires_at", "method_version", "evidence")
HISTORY_SQL = "/*asking:history*/ insert into tcg.reference_asking_history (" + ",".join((*SNAPSHOT_COLUMNS, "run_id", "actor_user_id")) + ") values (" + ",".join(f"${i}" for i in range(1, 19)) + ") returning snapshot_id"
CACHE_SQL = "/*asking:cache*/ insert into tcg.reference_asking_prices (" + ",".join(SNAPSHOT_COLUMNS) + ") select " + ",".join(SNAPSHOT_COLUMNS) + " from tcg.reference_asking_history where snapshot_id=$1 on conflict (provider,system_code,language,provider_id) do update set " + ",".join(f"{key}=excluded.{key}" for key in SNAPSHOT_COLUMNS if key not in KEYS) + " returning snapshot_id"


class BackfillStop(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def utcnow():
    return datetime.now(timezone.utc)


def cursor_for(reference):
    return [str(reference[key]) for key in KEYS]


def validated_cursor(value):
    if value is None:
        return ["", "", "", ""]
    if not isinstance(value, list) or len(value) != 4 or any(not isinstance(v, str) or len(v) > 512 for v in value):
        raise BackfillStop("INVALID_RESUME_CURSOR")
    return value


def identity_fingerprint(reference):
    material = {key: reference.get(key) for key in (*KEYS, *IDENTITY, "evidence", "reference_group_count")}
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def normalize_reference_keys(reference_keys):
    """Bound exact acquisition targets; never infer identity from a search term."""
    if reference_keys is None:
        return None
    if (not isinstance(reference_keys, (list, tuple))
            or not 1 <= len(reference_keys) <= MAX_TARGET_REFERENCES):
        raise ValueError(f"Select 1..{MAX_TARGET_REFERENCES} exact reference keys")
    normalized = []
    for key in reference_keys:
        if (not isinstance(key, (list, tuple)) or len(key) != len(KEYS)
                or any(not isinstance(part, str) or not part or len(part) > 512
                       or part != part.strip() or not part.isprintable() for part in key)
                or key[1] not in GAMES):
            raise ValueError("Each reference key must contain provider, supported system, language and provider ID")
        normalized.append(tuple(key))
    result = [list(key) for key in sorted(set(normalized))]
    if len(json.dumps(result, ensure_ascii=False).encode()) > 4000:
        raise ValueError("Reference selection is too large for the durable run scope")
    return result


def acquisition_scope(*, system_code=None, language=None, include_priced=False, reference_keys=None):
    if type(include_priced) is not bool:
        raise ValueError("include_priced must be a boolean")
    if system_code is not None and system_code not in GAMES:
        raise ValueError("Unsupported system filter")
    if language is not None and (not isinstance(language, str) or not language
            or len(language) > 64 or language != language.strip() or not language.isprintable()):
        raise ValueError("Invalid language filter")
    targets = normalize_reference_keys(reference_keys)
    if targets and any((system_code is not None and key[1] != system_code)
                       or (language is not None and key[2] != language) for key in targets):
        raise ValueError("Reference selection conflicts with the system or language filter")
    # Omit inactive options so pre-existing missing-only runs resume unchanged.
    scope = {"system_code": system_code, "language": language}
    if include_priced:
        scope["include_priced"] = True
    if targets is not None:
        scope["reference_keys"] = targets
    return scope


def benchmark_digest(postcode):
    if not isinstance(postcode, str) or not postcode.strip():
        raise BackfillStop("SHOP_DELIVERY_BENCHMARK_REQUIRED")
    return hashlib.sha256(("GB:" + re.sub(r"\s+", "", postcode.upper())).encode()).hexdigest()


def search_query(reference):
    # Provider checklist labels include long deck/marketing names that sellers
    # rarely repeat. Retrieve by game/card; the unchanged estimator
    # still requires exact set/printing proof before accepting any listing.
    # Language is often available only in item details. It remains mandatory
    # matching evidence, but including it in q hides those legitimate listings.
    value = " ".join(str(v).strip() for v in (GAMES.get(reference["system_code"], ""),
        reference["name"], reference["card_number"]) if v)
    value = " ".join(value.split())
    if not value or len(value) > 100:
        raise BackfillStop("QUERY_EXCEEDS_BROWSE_LIMIT")
    return value


def _summary_rank(row, reference, spec):
    """Reject explicit conflicts; absent detail-resolvable facts remain eligible."""
    title = _text(row.get("title"))
    aspects = _aspects(row)
    all_text = " ".join((title, _text(row.get("condition")), " ".join(aspects.values())))
    grade_text = re.sub(r"\bnot(?:\s+professionally)?\s+graded\b", "", all_text)
    if (_GRADE_RE.search(grade_text) or re.search(r"\bslabs\b", grade_text)
            or str(row.get("conditionId")) == "2750" or _MULTI_RE.search(all_text)):
        return None
    if any(aspects.get(key) not in (None, "", "no", "ungraded", "not graded", "not professionally graded")
           for key in ("professional grader", "grade", "certification number", "graded")):
        return None
    if (not all(token in title.split() for token in _text(reference["name"]).split())
            or _explicitly_denies(title, (reference["name"],))
            or not _number_matches(str(row.get("title", "")), aspects.get("card number", ""), reference["card_number"])):
        return None
    language_text = " ".join((title, aspects.get("language", "")))
    languages = {language for language, aliases in _LANGUAGES.items()
                 if any(_phrase(language_text, alias) for alias in aliases)}
    if ((languages and languages != {spec["language"]})
            or _explicitly_denies(language_text, _LANGUAGES[spec["language"]])):
        return None
    set_text = " ".join((title, aspects.get("set", "")))
    options = spec["set_alternatives"]
    terms = tuple(term for option in options for term in option)
    if (_explicitly_denies(set_text, terms)
            or any(_phrase(set_text, term) for term in spec["set_conflicts"])
            or (aspects.get("set") and not any(all(_text(term) == aspects["set"] for term in option) for option in options))):
        return None
    for base, expanded in (("base set", "base set 2"), ("team rocket", "team rocket returns")):
        if any(_text(term) == base for term in spec["set_terms"]) and _phrase(set_text, expanded):
            return None
    allowed_codes = {match.group().casefold() for match in _SET_CODES.finditer(" ".join((*spec["set_terms"], reference["card_number"])))}
    if any(match.group().casefold() not in allowed_codes for match in _SET_CODES.finditer(str(row.get("title", "")))):
        return None
    if (_variant_markers(all_text) - spec["markers"]
            or any(_explicitly_denies(all_text, _SPECIAL_MARKERS[marker]) for marker in spec["markers"])
            or _explicitly_denies(title, spec["variant_terms"])):
        return None
    known_finish = _listing_finish(row, {**spec, "finish": None})
    if (known_finish is not None and spec["finish"] in {"normal", "holo", "reverse", "foil"}
            and known_finish != spec["finish"]):
        return None
    # This is only request ordering. Every fetched response is still assessed
    # independently, without borrowing any missing fact from its summary.
    return (_matches(row, reference, spec) is None, languages == {spec["language"]},
            any(all(_phrase(set_text, term) for term in option) for option in options),
            _listing_finish(row, spec) is not None, _condition_matches(all_text))


def item_detail_candidates(reference, summaries, *, limit=MAX_ITEM_DETAILS_PER_CARD):
    """Select bounded discovery IDs, never turn search metadata into evidence.

    The unchanged estimator requires the exact card name in the title. Requiring
    its number too avoids spending detail calls on broad same-name matches.
    Missing language, finish, set and condition may be supplied by getItem.
    Skip explicit conflicts and rank stronger identity hints first. Prefer
    distinct sellers, but do not infer seller identity when absent. The default
    remains six details; a bounded manual probe may request up to 24 within its
    separate global request budget.
    """
    if type(limit) is not int or not 1 <= limit <= 24:
        raise ValueError("Detail candidate limit must be an integer from 1 to 24")
    spec, reason = _reference_spec(reference)
    if reason is not None or spec is None:
        return []
    candidates, seen_items = [], set()
    for position, row in enumerate(summaries):
        if not isinstance(row, dict):
            continue
        item_id = row.get("itemId")
        match = re.fullmatch(r"v1\|([1-9][0-9]{0,19})\|(0|[1-9][0-9]{0,19})", item_id or "") if isinstance(item_id, str) else None
        if match is None or match[1] in seen_items:
            continue
        rank = _summary_rank(row, reference, spec)
        if rank is None:
            continue
        seen_items.add(match[1])
        seller = row.get("seller")
        username = seller.get("username") if isinstance(seller, dict) else None
        seller_key = username.strip().casefold() if isinstance(username, str) and username.strip() else item_id
        candidates.append((rank, position, item_id, seller_key))
    candidates.sort(key=lambda candidate: (tuple(-int(value) for value in candidate[0]), candidate[1]))
    distinct, repeated, seen_sellers = [], [], set()
    for _, _, item_id, seller in candidates:
        if seller in seen_sellers:
            repeated.append(item_id)
        else:
            seen_sellers.add(seller)
            distinct.append(item_id)
    return (distinct + repeated)[:limit]


def bounded_item_detail(payload, item_id):
    """Keep only matcher inputs in memory, and bind them to the discovered ID.

    Never merge missing detail fields from the earlier search summary: the
    complete response is the current listing evidence. Descriptions, contact
    details and unrelated seller data are not retained or written to reports.
    """
    if not isinstance(payload, dict) or payload.get("itemId") != item_id:
        return None
    fields = ("itemId", "title", "condition", "conditionId", "conditionDescriptors",
              "localizedAspects", "localizedItemAspects", "price", "buyingOptions",
              "shippingOptions", "itemLocation", "currentBidPrice", "bidCount", "itemEndDate",
              "estimatedAvailabilities")
    row = {key: payload[key] for key in fields if key in payload}
    row["_evidence_acquisition"] = "GET_ITEM"
    seller = payload.get("seller")
    if isinstance(seller, dict) and isinstance(seller.get("username"), str):
        row["seller"] = {"username": seller["username"]}
    return row


def quota_windows(payload, *, now):
    """Validate every window of exact buy.browse, never the unrelated bulk API."""
    if not isinstance(payload, dict) or not isinstance(payload.get("rateLimits"), list):
        raise BackfillStop("INVALID_ANALYTICS_QUOTA")
    windows = []
    for group in payload["rateLimits"]:
        if not isinstance(group, dict):
            raise BackfillStop("INVALID_ANALYTICS_QUOTA")
        if str(group.get("apiContext", "")).lower() != "buy" or str(group.get("apiName", "")).lower() != "browse":
            continue
        resources = group.get("resources")
        if not isinstance(resources, list):
            raise BackfillStop("INVALID_ANALYTICS_QUOTA")
        for resource in resources:
            if not isinstance(resource, dict):
                raise BackfillStop("INVALID_ANALYTICS_QUOTA")
            if resource.get("name") != "buy.browse":
                continue
            rates = resource.get("rates")
            if not isinstance(rates, list) or not rates:
                raise BackfillStop("INVALID_ANALYTICS_QUOTA")
            for rate in rates:
                if not isinstance(rate, dict):
                    raise BackfillStop("INVALID_ANALYTICS_QUOTA")
                limit, remaining, count, window = (rate.get(k) for k in ("limit", "remaining", "count", "timeWindow"))
                if (any(type(v) is not int for v in (limit, remaining, count, window)) or limit < 1
                        or not 0 <= remaining <= limit or not 0 <= count <= limit or remaining + count > limit
                        or not 1 <= window <= 31_536_000):
                    raise BackfillStop("INVALID_ANALYTICS_QUOTA")
                try:
                    reset = datetime.fromisoformat(rate["reset"].replace("Z", "+00:00"))
                except (KeyError, TypeError, ValueError, AttributeError):
                    raise BackfillStop("INVALID_ANALYTICS_QUOTA") from None
                if reset.tzinfo is None or reset <= now or (reset-now).total_seconds() > window + 300:
                    raise BackfillStop("INVALID_ANALYTICS_QUOTA")
                windows.append({"limit": limit, "remaining": remaining, "count": count,
                                "time_window_seconds": window, "reset": reset.isoformat()})
    if not windows or len(windows) > 20:
        raise BackfillStop("BROWSE_QUOTA_UNAVAILABLE")
    return windows


def allow_quota_request(windows, used, now):
    if not windows or any(datetime.fromisoformat(w["reset"]) <= now for w in windows):
        raise BackfillStop("QUOTA_WINDOW_EXPIRED")
    if any(w["remaining"] - used - 1 < HEADROOM for w in windows):
        raise BackfillStop("BROWSE_QUOTA_HEADROOM")


def conservative_quota_windows(windows, budget):
    """Retain durable provider-window allowances across every invocation."""
    total = budget["total_requests"]
    if type(total) is not int or total < 0:
        raise BackfillStop("INVALID_DURABLE_QUOTA")
    current = deepcopy(windows)
    for window in current:
        window["provider_remaining"] = window["remaining"]
    for receipt in budget["receipts"]:
        saved = receipt["report"]
        if isinstance(saved, str):
            saved = json.loads(saved)
        prior = saved.get("quota", {})
        marker = prior.get("global_requests_at_refresh")
        # Pre-upgrade snapshots have no global reservation anchor. Deduct all
        # recorded attempts, conservatively, until their provider window resets.
        if marker is None:
            used = total
        elif type(marker) is not int or not 0 <= marker <= total:
            raise BackfillStop("INVALID_DURABLE_QUOTA")
        else:
            used = total - marker
        for previous in prior.get("windows", []):
            for window in current:
                if (previous.get("reset"), previous.get("time_window_seconds")) == (
                        window["reset"], window["time_window_seconds"]):
                    remaining = previous.get("remaining")
                    if type(remaining) is not int:
                        raise BackfillStop("INVALID_DURABLE_QUOTA")
                    window["remaining"] = min(window["remaining"], remaining-used)
    return current


async def refreshed_quota(store, client, *, quota_reader, clock):
    windows = quota_windows(await quota_reader(client), now=clock())
    budget = await store.quota_budget(windows)
    return {"resource": "buy.browse", "headroom": HEADROOM,
            "windows": conservative_quota_windows(windows, budget),
            "global_requests_at_refresh": budget["total_requests"]}


async def read_browse_quota(client):
    token = await client.application_token()
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as http:
            response = await http.get("https://api.ebay.com/developer/analytics/v1_beta/rate_limit/",
                params={"api_context": "buy", "api_name": "browse"},
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        if response.status_code != 200:
            raise BackfillStop("ANALYTICS_HTTP_" + str(response.status_code))
        if len(response.content) > 1_000_000:
            raise BackfillStop("INVALID_ANALYTICS_QUOTA")
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise BackfillStop("ANALYTICS_UNAVAILABLE") from None


def compact_evidence(estimate, reference, digest):
    comparables = estimate.get("comparables", [])
    if not isinstance(comparables, list) or not 3 <= len(comparables) <= 100:
        raise BackfillStop("INVALID_ESTIMATE_SAMPLE")
    rows = [{key: row[key] for key in ("item_id", "seller_hash", "price_gbp_minor", "shipping_gbp_minor")}
            | {"title": str(row.get("title", ""))[:80],
               "listing_evidence": row.get("listing_evidence", {})} for row in comparables]
    evidence = {"source": "EBAY_OFFICIAL_BROWSE", "shipping_basis": "ITEM_PLUS_SHIPPING",
        "matching_reference_evidence": matching_reference_evidence(reference),
        "reference_group_count": reference["reference_group_count"],
        "shipping_context": CONTEXT, "benchmark_digest": digest, "condition": "Near Mint",
        "finish": estimate["selected_finish"], "confidence": estimate["confidence"],
        "physical_valuation_eligible": False, "observed_at": estimate["observed_at"],
        "method_version": estimate["method_version"], "reference_identity": estimate["identity"],
        "match_proof": comparables[0].get("match_proof", {}), "comparables": rows,
        "estimate_low_minor": estimate["estimate_low_minor"], "estimate_minor": estimate["estimate_minor"],
        "estimate_high_minor": estimate["estimate_high_minor"], "sample_count": estimate["sample_count"],
        "seller_count": estimate["seller_count"], "query": search_query(reference)}
    # Include JSONB's whitespace overhead in the bound, keeping every member
    # used for the median instead of silently truncating the audit sample.
    if len(json.dumps(evidence, ensure_ascii=False).encode()) > 32_000:
        raise BackfillStop("EVIDENCE_SIZE_LIMIT")
    return evidence


def _bump(report, key, count=1):
    report["rejections"][key] = report["rejections"].get(key, 0) + count


def add_review_examples(report, reference, summaries, estimate, observed):
    """Tiny public review samples; never raw sellers or a partial median history."""
    identity = {key: reference.get(key) for key in (*KEYS, "name", "card_number", "set_name")}
    field = "preview" if estimate["status"] == "READY" else "rejection_examples"
    current = report.get(field, [])
    if estimate["status"] == "READY":
        if len(current) >= 3:
            return
        example = {"reference": identity, "estimate_minor": estimate["estimate_minor"],
                   "finish": estimate["selected_finish"], "confidence": estimate["confidence"],
                   "sample_count": estimate["sample_count"], "comparables": [
                       {"item_id": str(row["item_id"])[:80], "title": str(row["title"])[:80],
                        "price_gbp_minor": row["price_gbp_minor"], "shipping_gbp_minor": row["shipping_gbp_minor"]}
                       for row in estimate["comparables"][:3]]}
    else:
        rows = [row for row in summaries if isinstance(row, dict)]
        row = next(iter(rows), {})
        # Empty searches are already counted; retain the bounded examples for
        # actual listings whose details can explain a matching failure.
        if not row:
            return
        detailed_reasons = {item.get("reason") for item in current
            if item.get("listing_evidence", {}).get("acquisition") == "GET_ITEM"}
        # Use the small receipt budget to show different actual failures.
        # A repeated missing-language example must not conceal a later finish
        # or set mismatch from the same set of retrieved listing details.
        single = None
        for candidate in rows:
            if candidate.get("_evidence_acquisition") != "GET_ITEM":
                continue
            candidate_estimate = estimate_reference_asking_price(
                reference, [candidate], observed_at=observed, now=observed)
            reason = next(iter(candidate_estimate["rejection_counts"]), candidate_estimate["status"])
            if reason not in detailed_reasons:
                row, single = candidate, candidate_estimate
                break
        if single is None:
            single = estimate_reference_asking_price(reference, [row], observed_at=observed, now=observed)
        reason = next(iter(single["rejection_counts"]), single["status"])
        if row.get("_evidence_acquisition") == "GET_ITEM" and reason in detailed_reasons:
            return
        # A full listing's actual fields are more useful than a discovery-only
        # rejection. Replace a summary sample rather than hiding detail proof
        # behind the first three missing-language/opaque-number summaries.
        if len(current) >= 3:
            if row.get("_evidence_acquisition") != "GET_ITEM":
                return
            replace = next((index for index, item in enumerate(current)
                if item.get("listing_evidence", {}).get("acquisition") != "GET_ITEM"), None)
            if replace is None:
                seen_reasons = set()
                for index, item in enumerate(current):
                    if item.get("reason") in seen_reasons:
                        replace = index
                        break
                    seen_reasons.add(item.get("reason"))
            if replace is None:
                return
            current = [item for index, item in enumerate(current) if index != replace]
        aspects = _aspects(row)
        example = {"reference": identity, "item_id": str(row.get("itemId", ""))[:80],
                   "title": str(row.get("title", ""))[:80],
                   "reason": reason,
                   "listing_evidence": {
                       "acquisition": row.get("_evidence_acquisition", "SEARCH_SUMMARY"),
                       "condition": row.get("condition"), "condition_id": row.get("conditionId"),
                       "aspects": {key: aspects[key] for key in
                                   ("game", "language", "card number", "set", "finish", "card condition")
                                   if key in aspects}}}
    proposed = deepcopy(report)
    proposed[field] = [*current, example]
    if len(json.dumps({k: proposed.get(k, []) for k in ("preview", "rejection_examples")}, ensure_ascii=False).encode()) <= 8000:
        report[field] = proposed[field]


class SqlBackfillStore:
    def __init__(self, connection, actor, *, clock=utcnow):
        self.connection, self.actor, self.clock = connection, actor, clock

    @asynccontextmanager
    async def transaction(self, *, readonly=False):
        async with self.connection.transaction(readonly=readonly):
            await self.connection.execute("select set_config('tcg.user_id',$1,true)", str(self.actor))
            await self.connection.execute("select set_config('tcg.request_id',$1,true)", "asking-backfill-" + str(uuid4()))
            await require_platform_admin(self.connection)
            yield

    async def capacity(self):
        state = await check_database_capacity(self.connection)
        if not state.refresh_allowed:
            raise BackfillStop(state.reason)

    async def candidates(self, cursor, scope, limit=100):
        async with self.transaction(readonly=True):
            rows = await self.connection.fetch(CANDIDATES_SQL, *validated_cursor(cursor), limit,
                                                scope.get("system_code"), scope.get("language"),
                                                scope.get("include_priced", False), scope.get("reference_keys"))
        return [dict(r) for r in rows]

    async def quota_budget(self, windows):
        # One snapshot pairs the monotone all-time reservation total with active
        # window receipts. The caller also holds the session backfill lock.
        resets = sorted({window["reset"] for window in windows})
        async with self.transaction(readonly=True):
            row = await self.connection.fetchrow("""
                select coalesce(sum(requests),0)::bigint as total_requests,
                  coalesce(jsonb_agg(jsonb_build_object('report',report)) filter (
                    where exists (
                      select 1 from jsonb_array_elements(
                        case when jsonb_typeof(report#>'{quota,windows}')='array'
                             then report#>'{quota,windows}' else '[]'::jsonb end
                       ) as quota_window
                      where quota_window->>'reset'=any($1::text[])
                    )
                  ),'[]'::jsonb) as receipts
                from tcg.reference_asking_runs
                """, resets)
        receipts = row["receipts"]
        if isinstance(receipts, str):
            receipts = json.loads(receipts)
        return {"total_requests": int(row["total_requests"]), "receipts": receipts}

    async def open_run(self, run_id, resume_run, *, apply, scope, digest, limit):
        async with self.transaction():
            prior = None
            if resume_run:
                prior = await self.connection.fetchrow("select * from tcg.reference_asking_runs where id=$1 for update", resume_run)
                if not prior or prior["actor_user_id"] != self.actor:
                    raise BackfillStop("RESUME_RUN_UNAVAILABLE")
                saved = prior["report"]
                if isinstance(saved, str):
                    saved = json.loads(saved)
                if (not isinstance(saved, dict) or saved.get("version") != 1 or saved.get("apply") != apply
                        or saved.get("scope") != scope or saved.get("benchmark_digest") != digest):
                    raise BackfillStop("RESUME_SCOPE_OR_MODE_CHANGED")
                validated_cursor(saved.get("cursor"))
                if prior["status"] == "RUNNING" and prior["budget_day"] == self.clock().date():
                    report = deepcopy(saved)
                    report.update(run_id=str(prior["id"]), status="RUNNING", max_queries=limit,
                                  session_requests=0, requests=int(prior["requests"]))
                    if report.get("pending"):
                        _bump(report, "PRIOR_AMBIGUOUS_ATTEMPT_SKIPPED")
                        report["pending"] = None
                    return report
                if prior["status"] == "RUNNING":
                    await self.capacity()
                    await self.connection.execute("update tcg.reference_asking_runs set status='STOPPED',finished_at=clock_timestamp() where id=$1", prior["id"])
            report = {"version": 1, "run_id": str(run_id), "status": "RUNNING", "apply": apply,
                "scope": scope, "benchmark_digest": digest, "shipping_context": CONTEXT,
                "max_queries": limit, "requests": 0, "session_requests": 0, "cursor": saved.get("cursor") if prior else None,
                "budget_day": self.clock().date().isoformat(),
                "previous_run_id": str(resume_run) if prior else None, "pending": None,
                "stats": {"scanned": 0, "collected": 0, "matched": 0, "written": 0, "summaries_seen": 0},
                "rejections": {}, "database_price_writes": 0, "inventory_writes": 0, "store_price_writes": 0}
            await self.capacity()
            await self.connection.execute("insert into tcg.reference_asking_runs(id,actor_user_id,report) values($1,$2,$3::jsonb)", run_id, self.actor, report)
            return report

    async def save(self, report):
        if len(json.dumps(report, ensure_ascii=False).encode()) > 15_500:
            raise BackfillStop("RUN_REPORT_SIZE_LIMIT")
        await self.capacity()
        saved = await self.connection.fetchval("update tcg.reference_asking_runs set report=$2::jsonb where id=$1 and status='RUNNING' returning id", UUID(report["run_id"]), report)
        if saved is None:
            raise BackfillStop("RUN_NO_LONGER_ACTIVE")

    async def checkpoint(self, report):
        async with self.transaction():
            await self.save(report)

    async def reserve(self, report, reference):
        if report.get("budget_day") != self.clock().date().isoformat():
            raise BackfillStop("UTC_DAY_CHANGED_RESUME_REQUIRED")
        updated = deepcopy(report)
        updated.update(cursor=cursor_for(reference), pending=cursor_for(reference))
        async with self.transaction():
            daily = await self.connection.fetchval("select coalesce(sum(requests),0)::integer from tcg.reference_asking_runs where budget_day=(clock_timestamp() at time zone 'UTC')::date")
            if daily >= MAX_DAILY:
                raise BackfillStop("DAILY_BROWSE_BUDGET_EXHAUSTED")
            await self.capacity()
            used = await self.connection.fetchval("select tcg.reserve_reference_asking_request($1)", UUID(report["run_id"]))
            updated.update(requests=int(used), session_requests=report["session_requests"] + 1)
            await self.save(updated)
        return updated  # Committed before the caller can make its HTTP request.

    async def result(self, report, reference, estimate):
        updated = deepcopy(report)
        updated["pending"] = None
        async with self.transaction():
            if estimate["status"] == "READY" and report["apply"]:
                current = await self.connection.fetchrow(CURRENT_SQL, *cursor_for(reference))
                reason = None
                if current is None or identity_fingerprint(dict(current)) != identity_fingerprint(reference):
                    reason = "REFERENCE_IDENTITY_CHANGED"
                elif current.get("has_current_asking") is True or (not current["needs_price"] and not (
                        report["scope"].get("include_priced") is True
                        and current.get("has_current_asking") is False)):
                    reason = "CURRENT_EVIDENCE_ALREADY_AVAILABLE"
                elif reference_asking_eligibility(dict(current)):
                    reason = "REFERENCE_NO_LONGER_ELIGIBLE"
                if reason:
                    _bump(updated, reason)
                else:
                    observed = datetime.fromisoformat(estimate["observed_at"])
                    expires = datetime.fromisoformat(estimate["expires_at"])
                    checked = self.clock()
                    if not observed <= checked < expires:
                        raise BackfillStop("ESTIMATE_EXPIRED_BEFORE_WRITE")
                    evidence = compact_evidence(estimate, reference, report["benchmark_digest"])
                    snapshot_id = uuid4()
                    values = (*cursor_for(reference), snapshot_id, {k: reference.get(k) for k in IDENTITY},
                        estimate["estimate_minor"], estimate["estimate_high_minor"], "GBP", estimate["sample_count"],
                        estimate["seller_count"], observed, checked, expires, estimate["method_version"], evidence,
                        UUID(report["run_id"]), self.actor)
                    await self.capacity()
                    await self.connection.fetchval(HISTORY_SQL, *values)
                    await self.capacity()
                    await self.connection.fetchval(CACHE_SQL, snapshot_id)
                    updated["stats"]["written"] += 1
                    if "funnel" in updated:
                        updated["funnel"]["estimates_persisted"] += 1
                    updated["database_price_writes"] += 1
            await self.save(updated)
        return updated

    async def finish(self, report):
        async with self.transaction():
            await self.save(report)
            await self.capacity()
            await self.connection.execute("update tcg.reference_asking_runs set status=$2,finished_at=clock_timestamp() where id=$1 and status='RUNNING'", UUID(report["run_id"]), report["status"])


async def execute_backfill(store, client, report, *, quota_reader=read_browse_quota,
                           checkpoint=lambda report: None, clock=utcnow, sleep=asyncio.sleep,
                           monotonic=time.monotonic, multi_query=False):
    """Orchestration separated from SQL so failure/commit ordering is testable.

    The opt-in Lovable-derived plan discovers more eBay summaries, but every
    Browse call still uses the existing durable quota reservation, and all
    final matches use the unchanged deterministic estimator.
    """
    windows, session_used, next_request, scanned = [], 0, 0.0, 0
    quota_baseline = 0
    deadline = monotonic() + MAX_RUN_SECONDS
    detail_cache = {}
    begin_funnel(report)
    for key in ("search_requests", "detail_requests", "details_observed", "detail_cache_hits"):
        report["stats"].setdefault(key, 0)
    if multi_query:
        report["discovery_strategy"] = "LOVABLE_MULTI_QUERY_RAILWAY_V1"
        report["stats"].setdefault("search_variants_used", 0)
        report["stats"].setdefault("distinct_summaries", 0)

    async def request(reference, operation, kind, *, first_search=True):
        """One shared reservation/rate/deadline path for *every* Browse GET."""
        nonlocal report, session_used, next_request, windows, quota_baseline
        if session_used >= report["max_queries"] or monotonic() >= deadline:
            return False, None
        delay = next_request - monotonic()
        if delay > 0:
            await sleep(delay)
        if monotonic() >= deadline:
            return False, None
        if session_used - quota_baseline >= QUOTA_REFRESH_REQUESTS:
            report["quota"] = await refreshed_quota(store, client, quota_reader=quota_reader, clock=clock)
            windows, quota_baseline = report["quota"]["windows"], session_used
            report["quota"]["session_requests_at_refresh"] = quota_baseline
            await store.checkpoint(report)
            checkpoint(report)
        if monotonic() >= deadline:
            return False, None
        allow_quota_request(windows, session_used - quota_baseline, clock())
        # Persist the call classification with its durable charge. A failed or
        # interrupted GET still consumes the slot and retains the card cursor.
        updated = deepcopy(report)
        updated["stats"][kind] += 1
        if kind == "search_requests" and first_search:
            updated["funnel"]["references_searched"] += 1
        report = await store.reserve(updated, reference)
        checkpoint(report)
        session_used += 1
        next_request = monotonic() + 1.0
        return True, await operation()

    try:
        report["quota"] = await refreshed_quota(store, client, quota_reader=quota_reader, clock=clock)
        windows = report["quota"]["windows"]
        await store.checkpoint(report)
        checkpoint(report)
        while session_used < report["max_queries"] and scanned < MAX_SCAN and monotonic() < deadline:
            rows = await store.candidates(report.get("cursor"), report["scope"], min(100, MAX_SCAN-scanned))
            if not rows:
                report["status"] = "COMPLETE"
                break
            for reference in rows:
                if session_used >= report["max_queries"] or scanned >= MAX_SCAN or monotonic() >= deadline:
                    break
                scanned += 1
                report["stats"]["scanned"] += 1
                reason = reference_asking_eligibility(reference)
                try:
                    query = search_query(reference) if reason is None else None
                except BackfillStop as exc:
                    reason = exc.code
                if reason:
                    report["cursor"] = cursor_for(reference)
                    _bump(report, reason)
                    continue
                if multi_query:
                    # Port of Lovable's diverse retrieval; no calls originate from
                    # Lovable itself. Each search and detail consumes one durable
                    # Railway reservation. Summary rows never prove identity.
                    queries = build_reference_search_plan(reference)
                    if not queries:
                        report["cursor"] = cursor_for(reference)
                        _bump(report, "MULTI_QUERY_IDENTITY_REQUIRED")
                        continue
                    summaries = []
                    seen_ids = set()
                    observed = clock()
                    performed_searches = 0
                    for query_variant in queries:
                        performed, payload = await request(
                            reference,
                            lambda q=query_variant: client.search_items(
                                query=q, limit=40, item_location_country="GB",
                                fixed_price_only=True),
                            "search_requests", first_search=performed_searches == 0,
                        )
                        if not performed:
                            break
                        performed_searches += 1
                        results = payload.get("itemSummaries", []) if isinstance(payload, dict) else None
                        if not isinstance(results, list) or len(results) > 40:
                            raise BackfillStop("INVALID_BROWSE_SUMMARIES")
                        report["stats"]["summaries_seen"] += len(results)
                        report["funnel"]["searches_returning_listings"] += bool(results)
                        report["funnel"]["candidates_discovered"] += len(results)
                        observed = min(observed, clock())
                        for row in results:
                            if not isinstance(row, dict):
                                continue
                            item_id = row.get("itemId")
                            if not isinstance(item_id, str) or item_id in seen_ids:
                                continue
                            seen_ids.add(item_id)
                            if len(summaries) < MAX_CANDIDATE_SUMMARIES:
                                summaries.append(row)
                        # Summary plausibility is insufficient: the first 40
                        # listings may all be wrong-set/graded/Japanese cards.
                        # Stop early only when >=5 independent sellers have
                        # already passed the existing *full* identity+condition
                        # matcher on their discovery summaries. Even then, the
                        # saved estimate still requires independently fetched
                        # getItem details and three post-outlier sellers.
                        spec, spec_reason = _reference_spec(reference)
                        exact_sellers = set()
                        if spec_reason is None:
                            for candidate in summaries:
                                if _matches(candidate, reference, spec) is not None:
                                    continue
                                seller = candidate.get("seller")
                                name = seller.get("username") if isinstance(seller, dict) else None
                                if isinstance(name, str) and name.strip():
                                    exact_sellers.add(name.strip().casefold())
                        if len(exact_sellers) >= EARLY_STOP_PLAUSIBLE:
                            break
                    if not performed_searches:
                        break
                    report["stats"]["search_variants_used"] += performed_searches
                    report["stats"]["distinct_summaries"] += len(summaries)
                    detail_limit = MAX_DETAILS_PER_REFERENCE
                else:
                    performed, payload = await request(reference, lambda: client.search_items(
                        query=query, limit=100, item_location_country="GB",
                        fixed_price_only=True), "search_requests")
                    if not performed:
                        break
                    observed = clock()
                    summaries = payload.get("itemSummaries", []) if isinstance(payload, dict) else None
                    if not isinstance(summaries, list) or len(summaries) > 100:
                        raise BackfillStop("INVALID_BROWSE_SUMMARIES")
                    report["stats"]["summaries_seen"] += len(summaries)
                    report["funnel"]["searches_returning_listings"] += bool(summaries)
                    report["funnel"]["candidates_discovered"] += len(summaries)
                    detail_limit = MAX_ITEM_DETAILS_PER_CARD
                report["stats"]["collected"] += 1
                # Search fields are discovery/diagnostics only. Missing item
                # aspects are retrieved through getItem before any acceptance.
                diagnostic = estimate_reference_asking_price(reference, summaries, observed_at=observed, now=observed)
                for code, count in diagnostic["rejection_counts"].items():
                    _bump(report, "SUMMARY_" + code, count)
                details = []
                selected_ids = item_detail_candidates(reference, summaries, limit=detail_limit)
                report["funnel"]["selected_detail_candidates"] += len(selected_ids)
                for item_id in selected_ids:
                    if item_id in detail_cache:
                        detail, acquired = detail_cache[item_id]
                        report["stats"]["detail_cache_hits"] += 1
                    else:
                        performed, payload = await request(reference, lambda: client.get_item(item_id), "detail_requests")
                        if not performed:
                            break
                        acquired = clock()
                        detail = bounded_item_detail(payload, item_id)
                        # Even an invalid response is cached to avoid repeating
                        # a charged ambiguous call during this invocation.
                        detail_cache[item_id] = (detail, acquired)
                        report["stats"]["details_observed"] += int(detail is not None)
                        report["funnel"]["full_details_retrieved"] += int(detail is not None)
                    if detail is None:
                        _bump(report, "DETAIL_ITEM_ID_MISMATCH")
                        continue
                    # Reusing a response never renews its evidence lifetime.
                    observed = min(observed, acquired)
                    details.append(detail)
                estimate = estimate_reference_asking_price(reference, details, observed_at=observed, now=clock())
                record_estimate(report, estimate)
                if estimate["status"] == "READY":
                    report["stats"]["matched"] += 1
                else:
                    _bump(report, estimate["status"])
                for code, count in estimate["rejection_counts"].items():
                    _bump(report, code, count)
                add_review_examples(report, reference, details or summaries, estimate, observed)
                report = await store.result(report, reference, estimate)
                checkpoint(report)
            else:
                continue
            break
        if report["status"] == "RUNNING":
            reason = ("REQUEST_LIMIT" if session_used >= report["max_queries"] else
                      "SCAN_LIMIT" if scanned >= MAX_SCAN else "TIME_LIMIT")
            report.update(status="INCOMPLETE", stop_reason=reason)
    except BackfillStop as exc:
        report.update(status="STOPPED", stop_reason=exc.code)
    except EbayApiError as exc:
        report.update(status="STOPPED", stop_reason="EBAY_PROVIDER_ERROR",
                      provider_status=exc.status_code, retry_after_seconds=exc.retry_after_seconds)
    except Exception as exc:
        report.update(status="FAILED", stop_reason="BACKFILL_OPERATION_FAILED", error_class=type(exc).__name__)
    report["finished_at"] = clock().isoformat()
    try:
        await store.finish(report)
    except Exception as exc:
        report["receipt_persistence_error"] = type(exc).__name__
    checkpoint(report)
    return report


async def backfill_reference_asking(pool, actor, client=None, *, run=False, apply=False, max_queries=25,
                                    resume_run=None, run_id=None, system_code=None, language=None,
                                    include_priced=False, reference_keys=None,
                                    postcode=None, checkpoint=lambda report: None, clock=utcnow,
                                    quota_reader=read_browse_quota, multi_query=False):
    if type(multi_query) is not bool:
        raise ValueError("multi_query must be a boolean")
    if type(max_queries) is not int or not 1 <= max_queries <= MAX_DAILY or (apply and not run):
        raise ValueError(f"Use 1..{MAX_DAILY} queries and explicit --run with --apply")
    scope = acquisition_scope(system_code=system_code, language=language,
                              include_priced=include_priced, reference_keys=reference_keys)
    actor = UUID(str(actor))
    run_id = UUID(str(run_id)) if run_id else uuid4()
    resume_run = UUID(str(resume_run)) if resume_run else None
    async with pool.acquire() as connection:
        store = SqlBackfillStore(connection, actor, clock=clock)
        if not run:
            if resume_run:
                raise ValueError("--resume-run requires --run")
            eligible, rejected = [], {}
            cursor, scanned = None, 0
            scan_limit = min(MAX_SCAN, max_queries * 20)
            while scanned < scan_limit and len(eligible) < max_queries:
                rows = await store.candidates(cursor, scope, min(100, scan_limit-scanned))
                if not rows:
                    break
                for reference in rows:
                    cursor = cursor_for(reference)
                    scanned += 1
                    reason = reference_asking_eligibility(reference)
                    try:
                        query = search_query(reference) if reason is None else None
                    except BackfillStop as exc:
                        reason = exc.code
                    if reason:
                        rejected[reason] = rejected.get(reason, 0) + 1
                        continue
                    eligible.append({"reference": dict(zip(KEYS, cursor_for(reference))), "query": query})
                    if len(eligible) == max_queries:
                        break
            report = {"status": "PLAN_ONLY", "run_id": str(run_id), "requests": 0, "database_writes": 0,
                      "max_queries": max_queries, "scope": scope, "candidates": eligible, "rejections": rejected}
            checkpoint(report)
            return report
        if client is None:
            raise BackfillStop("OFFICIAL_EBAY_CLIENT_REQUIRED")
        digest = benchmark_digest(postcode)
        locked = await connection.fetchval("select pg_try_advisory_lock(hashtextextended($1,0))", LOCK_NAME)
        if not locked:
            raise BackfillStop("BACKFILL_ALREADY_RUNNING")
        try:
            report = await store.open_run(run_id, resume_run, apply=apply, scope=scope, digest=digest, limit=max_queries)
            checkpoint(report)
            desired_strategy = ("LOVABLE_MULTI_QUERY_RAILWAY_V1" if multi_query else "LEGACY_SINGLE_QUERY")
            saved_strategy = report.get("discovery_strategy", "LEGACY_SINGLE_QUERY")
            if resume_run and saved_strategy != desired_strategy:
                raise BackfillStop("DISCOVERY_STRATEGY_MISMATCH")
            report["discovery_strategy"] = desired_strategy
            return await execute_backfill(store, client, report, quota_reader=quota_reader,
                                          checkpoint=checkpoint, clock=clock, multi_query=multi_query)
        finally:
            await connection.fetchval("select pg_advisory_unlock(hashtextextended($1,0))", LOCK_NAME)


