begin;

-- A repeat fetch of the same FX publication is not new market evidence.
-- Keep its latest retrieval time in the current cache, while preserving every
-- existing history row and recording all substantive evidence changes.
create or replace function tcg.record_reference_market_history() returns trigger
language plpgsql security definer set search_path=pg_catalog as $$
declare
 old_evidence jsonb;
 new_evidence jsonb;
begin
 if TG_OP='UPDATE'
    and (old.provider,old.system_code,old.language,old.provider_id)
        is not distinct from (new.provider,new.system_code,new.language,new.provider_id)
    and old.market_value_minor is not distinct from new.market_value_minor
    and old.market_value_high_minor is not distinct from new.market_value_high_minor
    and old.pricing_updated_at is not distinct from new.pricing_updated_at then
  select coalesce(jsonb_agg(q.value-'fx_retrieved_at' order by q.ordinality),'[]'::jsonb)
    into old_evidence from jsonb_array_elements(old.quotes) with ordinality as q;
  select coalesce(jsonb_agg(q.value-'fx_retrieved_at' order by q.ordinality),'[]'::jsonb)
    into new_evidence from jsonb_array_elements(new.quotes) with ordinality as q;
  if old_evidence is not distinct from new_evidence then
   return new;
  end if;
 end if;

 insert into tcg.reference_market_history(reference_kind,provider,system_code,language,provider_id,
  quotes,quote_digest,market_value_minor,market_value_high_minor,pricing_updated_at)
 values(TG_ARGV[0],new.provider,new.system_code,new.language,new.provider_id,new.quotes,md5(new.quotes::text),
  new.market_value_minor,new.market_value_high_minor,new.pricing_updated_at)
 on conflict(reference_kind,provider,system_code,language,provider_id,quote_digest) do nothing;
 return new;
end;$$;
revoke all on function tcg.record_reference_market_history() from public,anon,authenticated,tcg_api;

commit;
