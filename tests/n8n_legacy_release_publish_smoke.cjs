'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {DatabaseSync}=require('node:sqlite');
const published=require('/opt/drop-rate/ops/guarded-legacy-release-publish.cjs');
const inspector=require('/opt/drop-rate/ops/inspect-stored-metadata.cjs');

function populate(temp) {
  const folder=path.join(temp,'user','.n8n');
  fs.mkdirSync(folder,{recursive:true,mode:0o700});
  const database=path.join(folder,'database.sqlite');
  const db=new DatabaseSync(database);
  db.exec('CREATE TABLE workflow_entity (id TEXT PRIMARY KEY,name TEXT,active INTEGER,activeVersionId TEXT,versionId TEXT,nodes TEXT,connections TEXT,settings TEXT,nodeGroups TEXT)');
  db.exec('CREATE TABLE workflow_history (workflowId TEXT,versionId TEXT,nodes TEXT,connections TEXT,nodeGroups TEXT)');
  const write=db.prepare('INSERT INTO workflow_entity VALUES(?,?,?,?,?,?,?,?,?)');
  const history=db.prepare('INSERT INTO workflow_history VALUES(?,?,?,?,?)');
  function insert(flow,activeVersionId=null){
    const id=flow.id,versionId='draft-'+id;
    write.run(id,flow.name,activeVersionId?1:0,activeVersionId,versionId,
      JSON.stringify(flow.nodes),JSON.stringify(flow.connections),JSON.stringify(flow.settings||{}),
      JSON.stringify(flow.nodeGroups||[]));
    history.run(id,versionId,JSON.stringify(flow.nodes),JSON.stringify(flow.connections),JSON.stringify(flow.nodeGroups||[]));
    if(activeVersionId)history.run(id,activeVersionId,JSON.stringify(flow.nodes),JSON.stringify(flow.connections),JSON.stringify(flow.nodeGroups||[]));
  }
  const control=JSON.parse(fs.readFileSync('/opt/drop-rate/workflows/dr-90-global-error.json','utf8'));
  insert(control,'published-control-v1');
  const sources=published.readSources();
  for(const row of sources)insert(row.source);
  db.close();
  return {folder,database,sources};
}
async function run(){
  const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'dr97-publish-smoke-'));
  try{
    const {folder,database,sources}=populate(tmp);
    const env={DROP_RATE_N8N_LEGACY_RELEASE_PUBLISH_ON_BOOT:'true',
      N8N_USER_FOLDER:path.dirname(folder),NODE_NO_WARNINGS:'1'};
    const state=published.readState(database,'',sources);
    assert.equal(state.length,8);
    assert(state.every(s=>!s.published&&!s.active));
    let calls=0;
    const command=async(args)=>{
      if(args[0]==='--version')return {stdout:'2.32.6\n'};
      assert.equal(args[0],'publish:workflow');
      const name=args[1].slice('--id='.length);
      assert(published.PLAN.some(row=>row[0]===name));
      const db=new DatabaseSync(database);
      const row=db.prepare('SELECT versionId FROM workflow_entity WHERE id=?').get(name);
      db.prepare('UPDATE workflow_entity SET activeVersionId=?, active=1 WHERE id=?').run(row.versionId,name);
      db.close();
      calls++;
      return {stdout:'Published'};
    };
    const offline=async()=>{};
    const result=await published.publish({env,command,offline});
    assert.equal(result.status,'PUBLISHED_VERIFIED',JSON.stringify(result));
    assert.equal(result.count,8);
    assert.equal(result.backup.verified,true);
    assert.equal(calls,8);
    const reread=published.readState(database,'',sources);
    assert.equal(reread.filter(s=>s.published).length,8);
    const duplicate=await published.publish({env,command:async()=>{throw Error('should not run')},offline});
    assert.equal(duplicate.status,'ALREADY_PUBLISHED');
    assert.equal(calls,8);
    const bad=await published.publish({env:{...env,DROP_RATE_N8N_LEGACY_RELEASE_PUBLISH_ON_BOOT:'Y'},
      command,offline});
    assert.equal(bad.status,'BLOCKED');
    assert.equal(bad.reason,'UNEXPECTED_FLAG');
    assert.equal(calls,8);
    const conflict=await published.publish({env:{...env,DROP_RATE_N8N_SUCCESS_RECEIPT_UPGRADE_ON_BOOT:'true'},
      command,offline});
    assert.equal(conflict.status,'BLOCKED');
    assert.equal(conflict.reason,'CONFLICTING_OPERATOR');
    assert.equal(calls,8);

    // An unexpected stored mutation must fail closed even after publication.
    const db=new DatabaseSync(database);
    const old=db.prepare('SELECT nodes FROM workflow_entity WHERE id=?').get(sources[0].id);
    db.prepare('UPDATE workflow_entity SET nodes=? WHERE id=?').run('[]',sources[0].id);
    db.close();
    const drift=await published.publish({env,command,offline});
    assert.equal(drift.status,'BLOCKED');
    assert.equal(drift.reason,'SOURCE_DRIFT');
    const restore=new DatabaseSync(database);
    restore.prepare('UPDATE workflow_entity SET nodes=? WHERE id=?').run(old.nodes,sources[0].id);
    restore.close();
    const report={event:'DR97_PINNED_OFFLINE_SMOKE',status:'VERIFIED',
      source_count:sources.length,publications:calls,idempotent:true,
      source_drift_blocked:true,conflicting_operators_blocked:true};
    process.stdout.write(JSON.stringify(report)+'\n');
  } finally {fs.rmSync(tmp,{recursive:true,force:true});}
}
run().catch(e=>{process.stderr.write('DR97_OFFLINE_SMOKE_FAILED '+e.message+'\n');process.exitCode=1;});
