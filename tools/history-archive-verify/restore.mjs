// Restore a downloaded archive into local, disposable PostgreSQL/WASM only.
// No network database connection or production credential is accepted.
import {PGlite} from '@electric-sql/pglite';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import crypto from 'node:crypto';

const root=path.resolve(process.argv[2]??'');
if(!process.argv[2]) throw Error('Usage: node restore.mjs ARCHIVE_DIRECTORY');
const watch=process.argv.includes('--watch');
const pg=new PGlite(path.join(root,'disposable-restore-pgdata'));
const hash=(data,algorithm='sha256')=>crypto.createHash(algorithm).update(data).digest('hex');
try {
 await pg.exec(`create schema tcg;
 create table tcg.reference_market_history (
 id uuid primary key,reference_kind text not null check(reference_kind in ('CARD','SEALED')),
 provider text not null,system_code text not null,language text not null,provider_id text not null,
 quotes jsonb not null check(jsonb_typeof(quotes)='array'),quote_digest text not null,
 market_value_minor bigint,market_value_high_minor bigint,pricing_updated_at timestamptz,
 recorded_at timestamptz not null,
 unique(reference_kind,provider,system_code,language,provider_id,quote_digest));`);
 let total=0;
 const rowHashes=new Map();
 const processed=new Set();
 while(true){
 const files=fs.readdirSync(path.join(root,'chunks')).filter(x=>x.endsWith('.manifest.json')&&!processed.has(x)).sort();
 for(const file of files){
  const m=JSON.parse(fs.readFileSync(path.join(root,'chunks',file),'utf8'));
  const gz=fs.readFileSync(path.join(root,'chunks',m.file_name));
  if(hash(gz)!==m.gzip_sha256)throw Error('Compressed checksum mismatch: '+file);
  const raw=zlib.gunzipSync(gz);
  if(hash(raw)!==m.sha256||raw.length!==m.raw_bytes)throw Error('Raw checksum mismatch: '+file);
  const lines=raw.toString('utf8').trimEnd().split('\n');
  if(lines.length!==m.row_count)throw Error('Row count mismatch: '+file);
  const expected=new Map();
  for(const line of lines){
   const row=JSON.parse(line);
   if(rowHashes.has(row.id))throw Error('Duplicate ID across chunks: '+row.id);
   expected.set(row.id,hash(line,'md5'));rowHashes.set(row.id,hash(line));
  }
  await pg.query(`insert into tcg.reference_market_history select * from json_populate_recordset(null::tcg.reference_market_history,$1::json)`,['['+lines.join(',')+']']);
  const rows=(await pg.query(`select id::text,md5(row_to_json(h)::text) as hash,md5(quotes::text)=quote_digest as quote_matches from tcg.reference_market_history h where id=any($1::uuid[])`,[Array.from(expected.keys())])).rows;
  if(rows.length!==lines.length)throw Error('Restored count mismatch');
  for(const row of rows)if(row.hash!==expected.get(row.id)||!row.quote_matches)throw Error('Restored fields differ: '+row.id);
  total+=rows.length;processed.add(file);console.log(JSON.stringify({restored:total,file}));
 }
 if(!watch)break;
 if(fs.existsSync(path.join(root,'export-complete.json'))){
  const expected=JSON.parse(fs.readFileSync(path.join(root,'export-complete.json'),'utf8'));
  if(total!==expected.row_count)throw Error('Full archive does not match expected database count');
  break;
 }
 await new Promise(resolve=>setTimeout(resolve,2000));
 }
 const full=crypto.createHash('sha256');
 for(const id of Array.from(rowHashes.keys()).sort())full.update(rowHashes.get(id));
 const latest=(await pg.query(`select count(*) as count,sum(octet_length(row_to_json(h)::text)) as raw_bytes from (select distinct on(reference_kind,provider,system_code,language,provider_id) * from tcg.reference_market_history order by reference_kind,provider,system_code,language,provider_id,recorded_at desc,id desc) h`)).rows[0];
 const receipt={verified_rows:total,content_root_sha256:full.digest('hex'),postgres:(await pg.query('select version() as version')).rows[0].version,latest_per_reference:latest,restore_verified:true};
 fs.writeFileSync(path.join(root,'restore-receipt.json'),JSON.stringify(receipt,null,2)+'\n');
 console.log(JSON.stringify(receipt));
} finally {await pg.close();}
