// Optional isolated PostgreSQL/WASM integration harness. No production access.
import fs from 'node:fs';
const { PGlite } = await import(process.env.BOOK_TEST_PGLITE_MODULE);
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const db = new PGlite();
await db.exec(`
create schema tcg;
create table tcg.catalogue_products (
 id uuid primary key, identity_key text unique not null, product_type text not null,
 game text, name text, set_name text, card_number text, variant text, rarity text,
 language text, created_at timestamptz default now());
create table tcg.catalogue_product_profiles (
 catalogue_id uuid primary key references tcg.catalogue_products(id), system_code text,
 collectible_type text, identity_status text, release_date date, attributes jsonb);
create table tcg.comic_printing_details (
 catalogue_id uuid primary key references tcg.catalogue_products(id), system_code text,
 series_title text, volume_identifier text, issue_number text, printing_number integer,
 release_year integer, cover_code text, cover_artist text, barcode_gtin text,
 identity_status text, attributes jsonb, version integer default 1,
 created_at timestamptz default now(), updated_at timestamptz default now());
create table tcg.provider_catalogue_mappings (
 id uuid primary key default gen_random_uuid(), catalogue_id uuid references tcg.catalogue_products(id),
 system_code text, source_provider text, provider_entity_type text, provider_id text,
 provider_variant_key text, provider_language text, source_reference text, match_status text,
 verification_basis text, confidence numeric, metadata jsonb,
 unique(source_provider,provider_entity_type,provider_id,provider_variant_key,provider_language));
`);
if (input.setup) await db.exec(input.setup);
const results = [];
for (const step of input.steps) {
  try {
    const values = await db.exec(step);
    results.push({ok: true, rows: values.flatMap(v => v.rows ?? [])});
  } catch (error) {
    results.push({ok: false, error: error.message});
    await db.exec('rollback;');
  }
}
const inspected = input.inspect ? (await db.query(input.inspect)).rows : [];
process.stdout.write(JSON.stringify({results, inspected}));
await db.close();
