-- Privileged operator repair. Replace both reviewed placeholders before execution.
-- Preserves all fields except the printed number/key and appended source proof.
begin;
set local lock_timeout='2s';
set local statement_timeout='15s';
do $repair$
declare
 v_actor uuid := '__ACTOR_USER_ID__'::uuid;
 v_expected text := '__SNAPSHOT_SHA256__';
 v_run uuid;
 v_request text := gen_random_uuid()::text;
 v_set jsonb;
 v_snapshot jsonb;
 v_digest text;
 v_before jsonb;
 v_after jsonb;
 v_card record;
 v_n integer;
 v_changed integer := 0;
 v_proof jsonb := '{"verification":"TCGDEX_REVIEWED_PRINTED_DENOMINATOR_V1","upstream_commit":"d09f7844f36b6cd69444650260372af490e9dbb7","upstream_file":"https://github.com/tcgdex/cards-database/blob/d09f7844f36b6cd69444650260372af490e9dbb7/data-asia/SV/SV11B.ts","printed_denominator":86,"total_cards":174}'::jsonb;
begin
 if v_expected !~ '^[0-9a-f]{64}$' then raise exception 'Reviewed snapshot digest required'; end if;
 perform set_config('tcg.user_id',v_actor::text,true);
 perform set_config('tcg.request_id',v_request,true);
 if tcg.is_platform_admin() is not true then raise exception 'Platform administrator required'; end if;
 if not pg_try_advisory_xact_lock(847220092) then raise exception 'Catalogue maintenance busy'; end if;
 if pg_database_size(current_database())>=400000000
    or current_setting('transaction_read_only')::boolean
    or current_setting('default_transaction_read_only')::boolean then
   raise exception 'Database capacity/write-mode blocked';
 end if;
 perform 1 from tcg.reference_sets where provider='TCGdex' and system_code='POKEMON_TCG'
   and language='Japanese' and set_id='SV11B' for update;
 if not found then raise exception 'SV11B set missing'; end if;
 perform 1 from tcg.reference_cards where provider='TCGdex' and system_code='POKEMON_TCG'
   and language='Japanese' and set_id='SV11B' order by provider_id for update;
 select to_jsonb(s) into v_set from tcg.reference_sets s
 where provider='TCGdex' and system_code='POKEMON_TCG' and language='Japanese' and set_id='SV11B';
 if v_set->>'name' is distinct from 'ブラックボルト'
   or v_set->>'declared_card_count' is distinct from '174'
   or v_set->>'source_url' is distinct from 'https://api.tcgdex.net/v2/ja/sets/SV11B' then
   raise exception 'SV11B set identity changed';
 end if;
 if (select count(*) from tcg.reference_cards where provider='TCGdex' and system_code='POKEMON_TCG'
   and language='Japanese' and set_id='SV11B')<>174 then raise exception 'Exactly 174 reference rows required'; end if;
 if (select count(*) from generate_series(1,174) n join tcg.reference_cards r
   on r.provider_id='SV11B-'||lpad(n::text,3,'0')
   and r.provider='TCGdex' and r.system_code='POKEMON_TCG' and r.language='Japanese' and r.set_id='SV11B')<>174 then
   raise exception 'Exact 174 reference IDs required';
 end if;
 if exists(select 1 from tcg.reference_cards r
   where provider='TCGdex' and system_code='POKEMON_TCG' and language='Japanese' and set_id='SV11B'
   and (source_url is distinct from 'https://api.tcgdex.net/v2/ja/cards/'||provider_id
    or evidence->>'provider_local_id' is distinct from substring(provider_id from 7)
    or name is null or btrim(name)=''
    or card_number is null or card_number not in (substring(provider_id from 7)||'/174',substring(provider_id from 7)||'/086')
    or number_key is distinct from (substring(provider_id from 7)::int)::text||':/:'||
       case when card_number like '%/174' then '174' else '86' end
    or (evidence ? 'collector_number_reference' and evidence->'collector_number_reference' is distinct from v_proof))) then
   raise exception 'Reference identity/number/evidence changed';
 end if;
 if not exists(select 1 from tcg.reference_cards where provider='TCGdex' and system_code='POKEMON_TCG'
   and language='Japanese' and set_id='SV11B' and card_number like '%/174') then return; end if;
 select jsonb_build_object('set',v_set,'cards',jsonb_agg(to_jsonb(r) order by provider_id))
 into v_snapshot from tcg.reference_cards r where provider='TCGdex' and system_code='POKEMON_TCG'
   and language='Japanese' and set_id='SV11B';
 v_digest := encode(sha256(convert_to(v_snapshot::text,'UTF8')),'hex');
 if v_digest<>v_expected then raise exception 'Snapshot changed; review again'; end if;
 insert into tcg.reference_sync_runs(source,status) values('tcgdex_sv11b_number_repair','RUNNING') returning id into v_run;
 for v_card in select * from tcg.reference_cards where provider='TCGdex' and system_code='POKEMON_TCG'
   and language='Japanese' and set_id='SV11B' and card_number like '%/174' order by provider_id
 loop
   v_before := to_jsonb(v_card);
   v_n := substring(v_card.provider_id from 7)::int;
   update tcg.reference_cards r set card_number=lpad(v_n::text,3,'0')||'/086',
     number_key=v_n::text||':/:86',
     evidence=r.evidence||jsonb_build_object('collector_number_reference',v_proof)
   where r.provider=v_card.provider and r.system_code=v_card.system_code and r.language=v_card.language
     and r.provider_id=v_card.provider_id and r.card_number=v_card.card_number and r.number_key=v_card.number_key
   returning to_jsonb(r) into v_after;
   if v_after is null or
     v_after is distinct from v_before||jsonb_build_object(
       'card_number',lpad(v_n::text,3,'0')||'/086','number_key',v_n::text||':/:86',
       'evidence',(v_before->'evidence')||jsonb_build_object('collector_number_reference',v_proof)) then
     raise exception 'Unexpected field changed';
   end if;
   insert into tcg.audit_events(actor,request_id,action,entity_type,entity_id,old_values,new_values)
    values(v_actor::text,v_request,'REFERENCE_COLLECTOR_NUMBER_CORRECTED','REFERENCE_SET_NUMBER_REPAIR',v_run,v_before,v_after);
   v_changed := v_changed+1;
 end loop;
 if (select count(*) from tcg.reference_cards where provider='TCGdex' and system_code='POKEMON_TCG'
   and language='Japanese' and set_id='SV11B' and card_number=substring(provider_id from 7)||'/086'
   and number_key=(substring(provider_id from 7)::int)::text||':/:86')<>174 then
   raise exception 'Postwrite 174-row check failed';
 end if;
 if (select count(*) from tcg.audit_events where entity_id=v_run and action='REFERENCE_COLLECTOR_NUMBER_CORRECTED')<>v_changed then
   raise exception 'Audit count mismatch';
 end if;
 update tcg.reference_sync_runs set status='COMPLETE',finished_at=clock_timestamp(),sets_loaded=1,cards_loaded=v_changed,
   report=jsonb_build_object('version','TCGDEX_SV11B_PRINTED_DENOMINATOR_V1','actor_user_id',v_actor,
    'request_id',v_request,'before_sha256',v_digest,'updated',v_changed,'already_correct',174-v_changed,
    'proof',v_proof,'pricing_changed',false,'physical_inventory_changed',false)
 where id=v_run;
end $repair$;
commit;
