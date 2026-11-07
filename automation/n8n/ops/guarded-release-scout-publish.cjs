'use strict';

// Explicit, guarded offline activation for six new *metadata-only* n8n scouts.
// Does not touch DR90/91/92/93/94/95, stored credentials, existing workflows,
// Supabase records, Shopify, R2 object bytes or commercial artwork permissions.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { backup } = require('node:sqlite');
const inspector = require('./inspect-stored-metadata.cjs');
const core = require('./guarded-control-plane-upgrade.cjs');

const FLAG = 'DROP_RATE_N8N_RELEASE_SCOUT_PUBLISH_ON_BOOT';
const EVENT = 'DROP_RATE_N8N_RELEASE_SCOUT_PUBLISH';
const VERSION = '2.32.6';
const DIRECTORY = path.resolve(__dirname, '..', 'workflows');
const PLAN = Object.freeze([
  ['DR96YugiohReleaseScoutV1', 'dr-96-ygoprodeck-release-scout.json'],
  ['DR96LorcanaReleaseScoutV1', 'dr-96-lorcast-release-scout.json'],
  ['DR96MagicReleaseScoutV1', 'dr-96-mtgjson-release-scout.json'],
  ['DR96SportsBowmanReleaseScoutV1', 'dr-96-cardcollectorcapital-release-scout.json'],
  ['DR96SportsHeritageReleaseScoutV1', 'dr-96-cardcollectorcapital-heritage-release-scout.json'],
  ['DR96FiguresReleaseScoutV1', 'dr-96-reviewed-figures-release-scout.json'],
]);
const FORBIDDEN_FLAGS = ['DROP_RATE_N8N_CONTROL_PLANE_UPGRADE_ON_BOOT',
  'DROP_RATE_N8N_SUCCESS_RECEIPT_UPGRADE_ON_BOOT',
  'DROP_RATE_N8N_SUCCESS_RECEIPT_PUBLISH_ON_BOOT',
  'DROP_RATE_N8N_HEARTBEAT_PAUSE_ON_BOOT',
  'DROP_RATE_R2_MEDIA_WORKFLOW_PUBLISH_ON_BOOT'];
const EXPECTED_SOURCES = ['ygoprodeck','lorcast','mtgjson',
  'cardcollectorcapital','cardcollectorcapital_heritage','reviewed_figures'];
const SAFE = new Set(['MISSING_WORKFLOW','SOURCE_DRIFT','UNEXPECTED_WORKFLOW_STATE',
  'ERROR_HANDLER_UNPUBLISHED','DATABASE_UNAVAILABLE','BACKUP_FAILED',
  'LOCK_UNAVAILABLE','CLI_FAILED','PUBLICATION_FAILED','N8N_OFFLINE_UNVERIFIED',
  'N8N_VERSION_MISMATCH','CONFLICTING_OPERATOR','UNEXPECTED_FLAG']);
function error(code) {const e = new Error(code);e.code=code;throw e;}
function result(status, fields={}) {
  return {event:EVENT,schema_version:1,status,...fields};
}
function parse(source) {
  if(typeof source!=='string'||source.length>1024*1024)error('SOURCE_DRIFT');
  try {return JSON.parse(source);}
  catch{error('SOURCE_DRIFT');}
}
function readSources(sourceDirectory=DIRECTORY) {
  const found = [];
  for(const [id,filename] of PLAN) {
    const location=path.join(sourceDirectory,filename);
    let stat;
    try{stat=fs.lstatSync(location);}catch{error('SOURCE_DRIFT');}
    if(!stat.isFile()||stat.isSymbolicLink()||stat.size>1024*1024)error('SOURCE_DRIFT');
    const source=parse(fs.readFileSync(location,'utf8'));
    if(source.id!==id||source.active!==false
      ||source.settings?.errorWorkflow!=='DR90GlobalErrorV1'
      ||source.nodes?.length!==4
      ||source.nodes.filter(n=>n.type==='n8n-nodes-base.scheduleTrigger').length!==1
      ||source.nodes.filter(n=>n.type==='n8n-nodes-base.httpRequest').length!==1
      ||source.nodes.filter(n=>n.type==='n8n-nodes-base.code').length!==2
      ||source.meta?.dropRate?.scope!=='metadata-only-verified-R2-source')
      error('SOURCE_DRIFT');
    const signer=source.nodes.find(n=>n.name.startsWith('Sign '))?.parameters?.jsCode || '';
    const verifier=source.nodes.find(n=>n.name.startsWith('Verify '))?.parameters?.jsCode || '';
    const expectedSource=source.meta.dropRate.source;
    if(!signer.includes("createHmac('sha256'")
      ||!signer.includes('REFRESH_APPROVED_RELEASE_SOURCE')
      ||!signer.includes('DROP_RATE_AUTOMATION_COMMAND_SECRET')
      ||!signer.includes("source:'"+expectedSource+"'")
      ||!signer.includes('/commands/catalogue/refresh-release-source')
      ||!verifier.includes("r.source!=='"+expectedSource+"'")
      ||!verifier.includes('r.artwork_published!==false')
      ||!verifier.includes('r.ownership_or_price_changed!==false'))
      error('SOURCE_DRIFT');
    found.push({id,source,sha:inspector.definitionHash(source)});
  }
  if(new Set(found.map(x=>x.id)).size!==PLAN.length
    ||new Set(found.map(x=>x.source.meta?.dropRate?.source)).size!==PLAN.length
    ||found.map(x=>x.source.meta.dropRate.source).join()!==EXPECTED_SOURCES.join())
    error('SOURCE_DRIFT');
  return found;
}
function safeJSON(value,fallback) {
  if(value==null)return fallback;
  if(typeof value!=='string'||value.length>1024*1024)error('UNEXPECTED_WORKFLOW_STATE');
  try{return JSON.parse(value);}
  catch{error('UNEXPECTED_WORKFLOW_STATE');}
}
function rowHash(row, version) {
  if(!row)error('MISSING_WORKFLOW');
  return inspector.definitionHash({
    id:row.id,name:row.name,nodes:safeJSON(version?.nodes??row.nodes,[]),
    connections:safeJSON(version?.connections??row.connections,{}),
    settings:safeJSON(row.settings,{}),nodeGroups:safeJSON(version?.nodeGroups??row.nodeGroups,[]),
  });
}
function readState(databasePath,prefix,source=readSources()) {
  if(!/^[A-Za-z0-9_]{0,64}$/.test(prefix))error('DATABASE_UNAVAILABLE');
  let db;
  try {
    const stat=fs.lstatSync(databasePath);
    if(!stat.isFile()||stat.isSymbolicLink())error('DATABASE_UNAVAILABLE');
    db=inspector.openDatabase(databasePath);
    db.exec('BEGIN');
    const tbl='"'+prefix+'workflow_entity"';
    const hist='"'+prefix+'workflow_history"';
    const query=db.prepare('SELECT id,name,active,activeVersionId,versionId,nodes,connections,settings,nodeGroups FROM '+tbl+' WHERE id=?');
    const vquery=db.prepare('SELECT nodes,connections,nodeGroups FROM '+hist+' WHERE workflowId=? AND versionId=?');
    const control=query.get('DR90GlobalErrorV1');
    if(!control||control.activeVersionId==null)error('ERROR_HANDLER_UNPUBLISHED');
    const controls=vquery.get(control.id,control.activeVersionId);
    const controlSource=parse(fs.readFileSync(path.resolve(__dirname,'..','workflows','dr-90-global-error.json'),'utf8'));
    if(!controls||rowHash(control,controls)!==inspector.definitionHash(controlSource))
      error('ERROR_HANDLER_UNPUBLISHED');
    return source.map(item=>{
      const row=query.get(item.id);
      if(!row)error('MISSING_WORKFLOW');
      if(![0,1].includes(row.active))error('UNEXPECTED_WORKFLOW_STATE');
      const stored=rowHash(row);
      if(stored!==item.sha)error('SOURCE_DRIFT');
      if(row.versionId==null||!vquery.get(row.id,row.versionId))error('UNEXPECTED_WORKFLOW_STATE');
      if(rowHash(row,vquery.get(row.id,row.versionId))!==item.sha)error('SOURCE_DRIFT');
      const published=row.activeVersionId!=null;
      if(row.active===1&&!published)error('UNEXPECTED_WORKFLOW_STATE');
      if(published){
        const version=vquery.get(row.id,row.activeVersionId);
        if(!version||rowHash(row,version)!==item.sha)error('UNEXPECTED_WORKFLOW_STATE');
      }
      return {id:item.id,sha:item.sha,active:row.active===1,published};
    });
  } catch(e) {
    if(SAFE.has(e.code))throw e;
    error('DATABASE_UNAVAILABLE');
  } finally {
    try{db?.exec('ROLLBACK');}catch{}
    try{db?.close();}catch{}
  }
}
function identity(rows) {
  return JSON.stringify(rows.map(x=>[x.id,x.sha,x.active,x.published]));
}
async function verifiedBackup(databasePath,states) {
  const parent=path.join(path.dirname(databasePath),'drop-rate-release-scout-backups');
  fs.mkdirSync(parent,{recursive:true,mode:0o700});
  const info=fs.lstatSync(parent);
  if(!info.isDirectory()||info.isSymbolicLink()||(info.mode&0o077))error('BACKUP_FAILED');
  const folder=fs.mkdtempSync(path.join(parent,'dr96-'));
  fs.chmodSync(folder,0o700);
  const dest=path.join(folder,'database.sqlite');
  fs.closeSync(fs.openSync(dest,'wx',0o600));
  let db,copy;
  try {
    db=inspector.openDatabase(databasePath);
    const pages=db.prepare('PRAGMA page_count').get().page_count;
    const size=db.prepare('PRAGMA page_size').get().page_size;
    if(pages*size>512*1024*1024)error('BACKUP_FAILED');
    await backup(db,dest,{rate:100});
    db.close();db=null;
    copy=inspector.openDatabase(dest);
    if(Object.values(copy.prepare('PRAGMA quick_check(1)').get()).join()!=='ok')
      error('BACKUP_FAILED');
    copy.close();copy=null;
    const digest=crypto.createHash('sha256');
    for await(const chunk of fs.createReadStream(dest))digest.update(chunk);
    const sha=digest.digest('hex');
    fs.writeFileSync(path.join(folder,'manifest.json'),JSON.stringify({
      plan:'dr96-source-scouts-v1',created_at:new Date().toISOString(),
      database_sha256:sha,states
    })+'\n',{flag:'wx',mode:0o600});
    return {verified:true,sha256:sha};
  }catch(e){
    if(SAFE.has(e.code))throw e;
    error('BACKUP_FAILED');
  }finally{try{db?.close();}catch{}try{copy?.close();}catch{}}
}
async function publish({env=process.env,sourceDirectory=DIRECTORY,command=core.cli,
                      offline=core.ensureOffline}={}) {
  let phase='PREFLIGHT',lock,lockPath;
  try{
    if(env[FLAG]!=='true')error('UNEXPECTED_FLAG');
    if(FORBIDDEN_FLAGS.some(x=>env[x]&&env[x]!=='false'))error('CONFLICTING_OPERATOR');
    const config=inspector.runtimeConfig(env);
    if(config.reason)error('DATABASE_UNAVAILABLE');
    const sources=readSources(sourceDirectory);
    phase='OFFLINE';
    try{await offline(env);}catch{error('N8N_OFFLINE_UNVERIFIED');}
    phase='STATE';
    const before=readState(config.databasePath,config.tablePrefix,sources);
    if(before.every(x=>x.published))return result('ALREADY_PUBLISHED',{count:PLAN.length});
    lockPath=path.join(path.dirname(config.databasePath),'release-scout-publish.lock');
    try{lock=fs.openSync(lockPath,'wx',0o600);}catch{error('LOCK_UNAVAILABLE');}
    fs.writeFileSync(lock,'dr96-source-scouts-v1\n');
    phase='VERSION';
    const version=await command(['--version'],env);
    if(version.stdout.trim()!==VERSION)error('N8N_VERSION_MISMATCH');
    phase='BACKUP';
    const receipt=await verifiedBackup(config.databasePath,before);
    phase='RECHECK';
    try{await offline(env);}catch{error('N8N_OFFLINE_UNVERIFIED');}
    if(identity(readState(config.databasePath,config.tablePrefix,sources))!==identity(before))
      error('UNEXPECTED_WORKFLOW_STATE');
    for(const item of before.filter(x=>!x.published)){
      phase='PUBLISH';
      try{await command(['publish:workflow','--id='+item.id],env);}
      catch{error('CLI_FAILED');}
      const checked=readState(config.databasePath,config.tablePrefix,sources);
      if(!checked.find(x=>x.id===item.id)?.published)error('PUBLICATION_FAILED');
    }
    const after=readState(config.databasePath,config.tablePrefix,sources);
    if(after.some(x=>!x.published))error('PUBLICATION_FAILED');
    return result('PUBLISHED_VERIFIED',{count:PLAN.length,backup:receipt});
  }catch(e){
    return result('BLOCKED',{phase,reason:SAFE.has(e.code)?e.code:'PUBLICATION_FAILED'});
  }finally{
    if(lock!==undefined){
      try{fs.closeSync(lock);}catch{}
      try{fs.unlinkSync(lockPath);}catch{}
    }
  }
}
if(require.main===module && process.argv[2]==='--verify-sources') {
  try {
    const source = readSources();
    process.stdout.write(JSON.stringify(result('SOURCE_VERIFIED',{count:source.length}))+'\n');
  }catch(e){
    process.stdout.write(JSON.stringify(result('BLOCKED',{reason:SAFE.has(e.code)?e.code:'SOURCE_DRIFT'}))+'\n');
    process.exitCode=1;
  }
} else if(require.main===module) {
  publish().then(r=>{
    process.stdout.write(JSON.stringify(r)+'\n');
    if(r.status==='BLOCKED')process.exitCode=1;
  }).catch(()=>{process.stdout.write(JSON.stringify(result('BLOCKED',{phase:'UNKNOWN',reason:'PUBLICATION_FAILED'}))+'\n');process.exitCode=1;});
}
module.exports={FLAG,PLAN,readSources,readState,identity,publish};
