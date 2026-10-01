begin;

alter table tcg.market_observations
  drop constraint if exists market_observations_source_check;
alter table tcg.market_observations
  add constraint market_observations_source_check
  check (source = any(array['EBAY','COLLECTR','TCGPLAYER','CARDMARKET','CARDTRADER','MANUAL']));

alter table tcg.market_source_mappings
  drop constraint if exists market_source_mappings_source_check;
alter table tcg.market_source_mappings
  add constraint market_source_mappings_source_check
  check (source = any(array['EBAY','COLLECTR','TCGPLAYER','CARDMARKET','CARDTRADER','MANUAL']));

alter table tcg.market_ingestion_runs
  drop constraint if exists market_ingestion_runs_source_check;
alter table tcg.market_ingestion_runs
  add constraint market_ingestion_runs_source_check
  check (source = any(array['EBAY','COLLECTR','TCGPLAYER','CARDMARKET','CARDTRADER']));

commit;
