select encode(sha256(convert_to(jsonb_build_object(
 'set',to_jsonb(s),
 'cards',(select jsonb_agg(to_jsonb(r) order by r.provider_id)
   from tcg.reference_cards r where r.provider=s.provider and r.system_code=s.system_code
   and r.language=s.language and r.set_id=s.set_id))::text,'UTF8')),'hex') as snapshot_sha256
from tcg.reference_sets s where s.provider='TCGdex' and s.system_code='POKEMON_TCG'
 and s.language='Japanese' and s.set_id='SV11B';