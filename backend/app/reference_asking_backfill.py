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
from .reference_asking_display import asking_cache_join, matching_reference_evidence, reference_number_alias as _number_alias
from .reference_asking_estimator import estimate_reference_asking_price, reference_asking_eligibility

KEYS = ("provider", "system_code", "language", "provider_id")
IDENTITY = ("name", "set_id", "card_number", "set_name", "finish", "rarity")
CONTEXT = "CONFIGURED_SHOP_POSTCODE_BENCHMARK"
MAX_DAILY = 500
HEADROOM = 500
MAX_SCAN = 5000
LOCK_NAME = "tcg.reference_asking_backfill"
GAMES = {"POKEMON_TCG": "Pokemon", "ONE_PIECE_CARD_GAME": "One Piece",
         "DRAGON_BALL_SUPER_FUSION_WORLD": "Fusion World",
         "DRAGON_BALL_SUPER_MASTERS": "DBS Masters",
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
SELECT_SQL = f"select r.*,s.name as set_name,{GROUP_COUNT},({NEEDS_PRICE}) as needs_price\n{FROM_SQL}"
CANDIDATES_SQL = SELECT_SQL + f"""where not ({DIGITAL_REFERENCE_SQL}) and r.language<>'Unknown'
 and ({NEEDS_PRICE}) and (r.provider,r.system_code,r.language,r.provider_id)>($1,$2,$3,$4)
 and ($6::text is null or r.system_code=$6) and ($7::text is null or r.language=$7)
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


def benchmark_digest(postcode):
    if not isinstance(postcode, str) or not postcode.strip():
        raise BackfillStop("SHOP_DELIVERY_BENCHMARK_REQUIRED")
    return hashlib.sha256(("GB:" + re.sub(r"\s+", "", postcode.upper())).encode()).hexdigest()


def search_query(reference):
    value = " ".join(str(v).strip() for v in (GAMES.get(reference["system_code"], ""),
        reference["name"], reference["card_number"], reference.get("set_name") or "", reference["language"]) if v)
    value = " ".join(value.split())
    if not value or len(value) > 100:
        raise BackfillStop("QUERY_EXCEEDS_BROWSE_LIMIT")
    return value


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
            | {"title": str(row.get("title", ""))[:80]} for row in comparables]
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
    if len(current) >= 3:
        return
    if estimate["status"] == "READY":
        example = {"reference": identity, "estimate_minor": estimate["estimate_minor"],
                   "finish": estimate["selected_finish"], "confidence": estimate["confidence"],
                   "sample_count": estimate["sample_count"], "comparables": [
                       {"item_id": str(row["item_id"])[:80], "title": str(row["title"])[:80],
                        "price_gbp_minor": row["price_gbp_minor"], "shipping_gbp_minor": row["shipping_gbp_minor"]}
                       for row in estimate["comparables"][:3]]}
    else:
        row = next((row for row in summaries if isinstance(row, dict)), {})
        single = estimate_reference_asking_price(reference, [row] if row else [], observed_at=observed, now=observed)
        example = {"reference": identity, "item_id": str(row.get("itemId", ""))[:80],
                   "title": str(row.get("title", ""))[:80],
                   "reason": next(iter(single["rejection_counts"]), single["status"])}
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
                                                scope.get("system_code"), scope.get("language"))
        return [dict(r) for r in rows]

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
                elif not current["needs_price"]:
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
                           monotonic=time.monotonic):
    """Orchestration separated from SQL so failure/commit ordering is testable."""
    windows, session_used, next_request, scanned = [], 0, 0.0, 0
    try:
        windows = quota_windows(await quota_reader(client), now=clock())
        report["quota"] = {"resource": "buy.browse", "headroom": HEADROOM, "windows": windows}
        await store.checkpoint(report)
        checkpoint(report)
        while session_used < report["max_queries"] and scanned < MAX_SCAN:
            rows = await store.candidates(report.get("cursor"), report["scope"], min(100, MAX_SCAN-scanned))
            if not rows:
                report["status"] = "COMPLETE"
                break
            for reference in rows:
                if session_used >= report["max_queries"] or scanned >= MAX_SCAN:
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
                delay = next_request - monotonic()
                if delay > 0:
                    await sleep(delay)
                allow_quota_request(windows, session_used, clock())
                report = await store.reserve(report, reference)
                checkpoint(report)
                session_used += 1
                next_request = monotonic() + 1.0
                payload = await client.search_items(query=query, limit=100, item_location_country="GB", fixed_price_only=True)
                observed = clock()
                summaries = payload.get("itemSummaries", []) if isinstance(payload, dict) else None
                if not isinstance(summaries, list) or len(summaries) > 100:
                    raise BackfillStop("INVALID_BROWSE_SUMMARIES")
                estimate = estimate_reference_asking_price(reference, summaries, observed_at=observed, now=observed)
                report["stats"]["collected"] += 1
                report["stats"]["summaries_seen"] += len(summaries)
                if estimate["status"] == "READY":
                    report["stats"]["matched"] += 1
                else:
                    _bump(report, estimate["status"])
                for code, count in estimate["rejection_counts"].items():
                    _bump(report, code, count)
                add_review_examples(report, reference, summaries, estimate, observed)
                report = await store.result(report, reference, estimate)
                checkpoint(report)
            else:
                continue
            break
        if report["status"] == "RUNNING":
            report.update(status="INCOMPLETE", stop_reason="REQUEST_LIMIT" if session_used >= report["max_queries"] else "SCAN_LIMIT")
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
                                    postcode=None, checkpoint=lambda report: None, clock=utcnow,
                                    quota_reader=read_browse_quota):
    if type(max_queries) is not int or not 1 <= max_queries <= MAX_DAILY or (apply and not run):
        raise ValueError("Use 1..500 queries and explicit --run with --apply")
    if system_code is not None and system_code not in GAMES:
        raise ValueError("Unsupported system filter")
    scope = {"system_code": system_code, "language": language}
    actor = UUID(str(actor))
    run_id = UUID(str(run_id)) if run_id else uuid4()
    resume_run = UUID(str(resume_run)) if resume_run else None
    async with pool.acquire() as connection:
        store = SqlBackfillStore(connection, actor, clock=clock)
        if not run:
            if resume_run:
                raise ValueError("--resume-run requires --run")
            rows = await store.candidates(None, scope, min(MAX_SCAN, max_queries * 20))
            eligible, rejected = [], {}
            for reference in rows:
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
            return await execute_backfill(store, client, report, quota_reader=quota_reader, checkpoint=checkpoint, clock=clock)
        finally:
            await connection.fetchval("select pg_advisory_unlock(hashtextextended($1,0))", LOCK_NAME)
