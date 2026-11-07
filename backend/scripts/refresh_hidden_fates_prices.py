"""Preview the exact 94-card Hidden Fates Shiny Vault catalogue price fill.

Dry-run by default. --apply writes only positive, proven catalogue guides.
It never writes inventory, owner valuations, or storefront prices.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.pokemon_subset_price_refresh import refresh_hidden_fates


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument('--actor-user-id', type=UUID)
    identity.add_argument('--from-settings', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--max-seconds', type=int, default=120)
    parser.add_argument('--report-file', type=Path)
    args = parser.parse_args()
    if not 1 <= args.max_seconds <= 240:
        parser.error('--max-seconds must be between 1 and 240')
    from app.cardtrader_client import CardTraderClient
    from app.db import create_pool
    from app.fx import EcbHistoricalFxProvider
    from app.settings import get_settings
    settings = get_settings()
    if not settings.cardtrader_api_token:
        parser.error('The existing CardTrader integration is not configured')
    actor = args.actor_user_id or UUID(settings.catalogue_maintenance_actor_user_id)
    pool = await create_pool(settings)
    try:
        report = await refresh_hidden_fates(pool, actor,
            CardTraderClient(api_token=settings.cardtrader_api_token, timeout_seconds=8),
            EcbHistoricalFxProvider(timeout_seconds=8),
            apply=args.apply, max_seconds=args.max_seconds)
    finally:
        await pool.close()
    if args.report_file:
        args.report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for row in report.get('preview', []):
        print('HIDDEN_FATES_PRICE_PREVIEW ' + json.dumps(row, ensure_ascii=True, sort_keys=True), flush=True)
    summary = {key: value for key, value in report.items() if key != 'preview'}
    print('HIDDEN_FATES_PRICE_FILL ' + json.dumps(summary, sort_keys=True), flush=True)
    return 0 if report['status'] in {'VERIFIED', 'COMPLETE'} else 2


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
