"""Explicit one-request publisher research probe; no database/account writes.

Run only for the book-research release using the existing configured model/key.
This public publisher cover tests the actual API tool/schema/source contract,
not photographed-copy accuracy. It must never run automatically per scan.
"""
import asyncio
import json
from pathlib import Path

from app.book_research import publisher_source, research_book
from app.recognition_vision import close_shared_vision_http_client
from app.settings import get_settings


def fixture_record(candidate, entry):
    # VIZ's paperback tab is a format-specific alias for this same print record.
    # Keep the product ID and ISBN exact; digital/other editions are not aliases.
    source = publisher_source(entry['source_url'])
    return (candidate.get('source_url') in {source, source + '/paperback'}
            and candidate.get('fields', {}).get('barcode_gtin') == entry['book']['barcode_gtin'])


def fixture_cover(candidate, entry):
    return (fixture_record(candidate, entry)
            and candidate.get('image_url') == entry['cover_source_url']
            and candidate.get('cover_matches_photo') is True)


async def main():
    settings = get_settings()
    entry = json.loads((Path(__file__).resolve().parents[1]/'data/book_catalogue_starter_20261016.json').read_text())['entries'][0]
    fields = {**entry['book'], 'language': entry['language']}
    try:
        result = await research_book(fields, [entry['cover_source_url']], api_key=settings.openai_api_key or '', model=settings.recognition_model)
        candidates = result.get('candidates', [])
        # Public fixture metadata only: expose the precise mismatch without
        # logging a real user's photographs, account, credentials or scan data.
        print('BOOK_PUBLIC_PROBE_DETAILS ' + json.dumps({
            'candidates': [{'source_url': c['source_url'],
                'barcode': c['fields'].get('barcode_gtin'),
                'image_url': c.get('image_url'),
                'cover_matches_photo': c.get('cover_matches_photo')}
                for c in candidates], 'database_writes': False}), flush=True)
        exact = [c for c in candidates if fixture_record(c, entry)]
        passed = any(fixture_cover(c, entry) for c in exact)
        print(json.dumps({'book_research_smoketest':'PASS' if passed else 'FAIL',
            'configured_model':settings.recognition_model,'research_status':result['status'],
            'provider_status':result.get('provider_status'),'candidate_count':len(candidates),
            'matching_publisher_record':bool(exact),'publisher_cover':passed,
            'source_url':entry['source_url'],'database_writes':False}),flush=True)
        return 0 if passed else 1
    finally:
        await close_shared_vision_http_client()


if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
