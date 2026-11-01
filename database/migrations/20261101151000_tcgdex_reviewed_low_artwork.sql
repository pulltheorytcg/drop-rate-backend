begin;

-- Four exact English TCGdex printings: their high.webp links returned 404,
-- while the same-provider/locale/set/local-ID low.webp bytes were retrieved,
-- decoded and visually checked against the printed name and number on 1 Nov.
-- No broad URL rewrite, cross-printing search, owner media, stock or price edit.
-- On an empty/test catalogue the guarded update is a harmless no-op.
with reviewed(provider_id,set_id,name,card_number,local_id,high_url,low_url,sha256) as (
 values
 ('sv03.5-163','sv03.5','Leftovers','163/165','163',
  'https://assets.tcgdex.net/en/sv/sv03.5/163/high.webp',
  'https://assets.tcgdex.net/en/sv/sv03.5/163/low.webp',
  'c6353512656a25d7c0ec6e30a9fc82c2759ecc03f37a9e17a03a134fefcae70b'),
 ('A2a-021','A2a','Abomasnow','021/75','021',
  'https://assets.tcgdex.net/en/tcgp/A2a/021/high.webp',
  'https://assets.tcgdex.net/en/tcgp/A2a/021/low.webp',
  'afc837a0a18d0d44a28e49e82795a81f53e5e326262848177f1d9c76973a250d'),
 ('ex14-97','ex14','Shiftry ex','97/100','97',
  'https://assets.tcgdex.net/en/ex/ex14/97/high.webp',
  'https://assets.tcgdex.net/en/ex/ex14/97/low.webp',
  'c6e2d64dfaa08b95cd5ca192389d840e67589c58ef654b94e72173aee5dce34f'),
 ('A3a-072','A3a','Blacephalon','072/69','072',
  'https://assets.tcgdex.net/en/tcgp/A3a/072/high.webp',
  'https://assets.tcgdex.net/en/tcgp/A3a/072/low.webp',
  '432a1a2ac577fde631be8bdb58525f84b3719daac3d2fd22c61d18bebfdcd804')
)
update tcg.reference_cards r set
 image_url=v.low_url,
 evidence=r.evidence || jsonb_build_object('image_reference',jsonb_build_object(
  'verification','TCGDEX_REVIEWED_LOW_WEBP_V1',
  'reviewed_at','2026-11-01',
  'review_method','EXACT_PRINTED_NAME_NUMBER_AND_RASTER',
  'source_url',r.source_url,
  'image_url',v.low_url,'original_high_url',v.high_url,
  'content_sha256',v.sha256,'width',245,'height',337,
  'scope','REFERENCE_ONLY_NOT_APPROVED_MEDIA')),
 refreshed_at=clock_timestamp()
from reviewed v
where r.provider='TCGdex' and r.system_code='POKEMON_TCG'
 and r.language='English' and r.provider_id=v.provider_id
 and r.set_id=v.set_id and r.name=v.name and r.card_number=v.card_number
 and r.evidence->>'provider_local_id'=v.local_id
 and r.source_url='https://api.tcgdex.net/v2/en/cards/'||v.provider_id
 and r.image_url=v.high_url
 and not (r.evidence ? 'image_reference');

commit;
