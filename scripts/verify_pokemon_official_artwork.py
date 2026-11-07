"""Build a resumable, verified image manifest; never writes to a database.

Usage: PYTHONPATH=backend python scripts/verify_pokemon_official_artwork.py
  --source /path/to/pinned/PTCG-database --refs refs.json --output manifest.json
The source checkout must be at SOURCE_COMMIT. Only factual identity/asset URLs
are read; card text and source images are not copied into the repository.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
from pathlib import Path
import subprocess
import warnings
from datetime import datetime, timezone

import httpx
from PIL import Image

from app.pokemon_official_artwork import (
    SOURCE_COMMIT, SOURCE_REPOSITORY, VERIFICATION, artwork_candidates,
)


async def verify(candidates, output):
    previous = json.loads(output.read_text()) if output.exists() else {}
    verified = {row['provider_id']: row for row in previous.get('entries', [])}
    failures = {}
    throttled = asyncio.Event()
    semaphore = asyncio.Semaphore(4)
    count = 0

    def save():
        data = {'source_repository': SOURCE_REPOSITORY, 'source_commit': SOURCE_COMMIT,
                'candidate_count': len(candidates), 'entries': list(verified.values()),
                'failures': failures, 'rate_limited': throttled.is_set()}
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
        temporary.replace(output)

    async with httpx.AsyncClient(timeout=10, follow_redirects=False,
                                 headers={'User-Agent': 'DropRate-ReferenceArtwork/1.0'}) as client:
        async def probe(row):
            nonlocal count
            old = verified.get(row['provider_id'])
            if old and all(old.get(key) == value for key, value in row.items()):
                return
            verified.pop(row['provider_id'], None)
            async with semaphore:
                if throttled.is_set():
                    return
                try:
                    async with client.stream('GET', row['image_url']) as response:
                        if response.status_code == 429:
                            throttled.set()
                        if response.status_code != 200:
                            raise ValueError(f'HTTP_{response.status_code}')
                        if response.headers.get('content-type', '').split(';')[0] not in {'image/jpeg','image/png'}:
                            raise ValueError('NOT_AN_IMAGE')
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 2_000_000:
                                raise ValueError('IMAGE_TOO_LARGE')
                    with warnings.catch_warnings():
                        warnings.simplefilter('error', Image.DecompressionBombWarning)
                        with Image.open(io.BytesIO(data)) as img:
                            width, height = img.size
                            if (img.format not in {'JPEG','PNG'} or min(width,height) < 200
                                    or width*height > 4_000_000 or not .55 <= width/height <= .8):
                                raise ValueError('INVALID_CARD_DIMENSIONS')
                            img.verify()
                    evidence = {
                        'verification': VERIFICATION, 'scope': 'REFERENCE_ONLY_NOT_APPROVED_MEDIA',
                        'provider': 'Pokemon Official', 'source_repository': SOURCE_REPOSITORY,
                        'source_commit': SOURCE_COMMIT, 'official_source_url': row['official_source_url'],
                        'official_card_id': row['official_card_id'], 'image_url': row['image_url'],
                        'match_basis': 'EXACT_JAPANESE_SET_NUMBER_TOTAL_NAME_UNIQUE_OFFICIAL_IMAGE',
                        'content_sha256': hashlib.sha256(data).hexdigest(),
                        'width': width, 'height': height, 'size_bytes': len(data),
                        'reference_source_url': row['source_url'],
                        'verified_at': datetime.now(timezone.utc).isoformat(),
                    }
                    verified[row['provider_id']] = {**row, 'evidence': evidence}
                except (httpx.HTTPError, ValueError, OSError, Image.DecompressionBombWarning) as exc:
                    failures[row['provider_id']] = type(exc).__name__ + ':' + str(exc)[:150]
                count += 1
                if count % 100 == 0:
                    save()
                    print(json.dumps({'probed': count, 'verified': len(verified), 'failed': len(failures)}), flush=True)

        await asyncio.gather(*(probe(row) for row in candidates))
    # Drop obsolete entries if the input catalogue changed between runs.
    live = {row['provider_id'] for row in candidates}
    verified = {key: value for key, value in verified.items() if key in live}
    save()
    print(json.dumps({'verified': len(verified), 'failed': len(failures), 'rate_limited': throttled.is_set()}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--refs', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    commit = subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != SOURCE_COMMIT:
        raise SystemExit('Source checkout does not match reviewed commit')
    sources = [json.loads(path.read_text()) for path in sorted((args.source/'data_jp').glob('*/*.json'))]
    candidates, rejected = artwork_candidates(json.loads(args.refs.read_text()), sources)
    print(json.dumps({'candidates': len(candidates), 'rejected': rejected}), flush=True)
    asyncio.run(verify(candidates, args.output))


if __name__ == '__main__':
    main()
