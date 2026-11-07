'use strict';
// Return only fixed categories. Never emit stdout, stderr, message, URL or env values.
function executionError(text){
 if(typeof text!=='string') return null;
 text=text.slice(0,8*1024*1024);
 let start=-1,depth=0,quoted=false,escaped=false,objects=0;
 for(let i=0;i<text.length;i++){
  const c=text[i];
  if(start<0){if(c==='{'){start=i;depth=1;}continue;}
  if(quoted){if(escaped)escaped=false;else if(c==='\\')escaped=true;else if(c==='"')quoted=false;continue;}
  if(c==='"'){quoted=true;continue;}
  if(c==='{')depth++;
  if(c==='}')depth--;
  if(depth===0){
   try{
    const value=JSON.parse(text.slice(start,i+1));
    const failure=value?.data?.resultData?.error;
    if(failure&&typeof failure==='object') return ['name','message','description'].map(k=>typeof failure[k]==='string'?failure[k].slice(0,4000):'').join('\n');
    if(value?.workflowData||value?.data?.resultData) return '';
   }catch{}
   start=-1;quoted=false;escaped=false;
   if(++objects>=16)break;
  }
 }
 return null;
}
function classify(error, phase){
 const phases=new Set(['CONFIG','IMPORT','EXECUTE','SUMMARY','CLEANUP']);
 const safePhase=phases.has(phase)?phase:'UNKNOWN';
 const structured=executionError(error?.stdout);
 let raw;
 if(structured!==null) raw=structured;
 else {
  const text=[error?.message,error?.stdout,error?.stderr].filter(v=>typeof v==='string').join('\n');
  // Truncated execution JSON is not permission to search its workflow code.
  raw=/"workflowData"|"jsCode"|"resultData"/.test(text)?'':text.slice(0,16000);
 }
 const codes=[
  'pilot_operator_configuration_missing','pilot_workflow_contract_invalid',
  'pilot_summary_missing','pilot_summary_identity_mismatch',
  'approved_pilot_hash_not_configured','approved_pilot_operation_invalid',
  'approved_pilot_backend_invalid','approved_pilot_signature_missing',
  'approved_pilot_response_identity_mismatch','approved_pilot_response_invalid',
  'approved_pilot_channel_results_incomplete',
 ];
 let reason='PILOT_RUNTIME_UNVERIFIED';
 const found=codes.find(code=>raw.includes(code));
 if(found) reason=found.toUpperCase();
 else if(/approved_pilot_backend_http_(401|403|404|409|413|422|429|500|502|503|504)\b/.test(raw)) reason='PILOT_BACKEND_HTTP_'+raw.match(/approved_pilot_backend_http_(401|403|404|409|413|422|429|500|502|503|504)\b/)[1];
 else if(/access to env vars denied|environment variable access.*denied/i.test(raw)) reason='N8N_ENV_ACCESS_DENIED';
 else if(/module ['"](?:node:)?crypto['"].*(?:disallowed|not allowed)|cannot find module ['"](?:node:)?crypto/i.test(raw)) reason='N8N_CRYPTO_UNAVAILABLE';
 else if(/SQLITE_CANTOPEN|SQLITE_READONLY|SQLITE_BUSY/.test(raw)) reason='N8N_TEMP_DATABASE_UNAVAILABLE';
 else if(/ENOTFOUND|EAI_AGAIN|getaddrinfo/i.test(raw)) reason='PILOT_DNS_UNAVAILABLE';
 else if(/ECONNREFUSED|ECONNRESET|ETIMEDOUT|connection.*timed out/i.test(raw)) reason='PILOT_NETWORK_UNAVAILABLE';
 else if(/task runner.*(?:timed out|unavailable)|task request timed out/i.test(raw)) reason='N8N_TASK_RUNNER_UNAVAILABLE';
 else if(error?.code==='ENOENT') reason='PILOT_EXECUTABLE_NOT_FOUND';
 else if(error?.code==='EACCES') reason='PILOT_FILESYSTEM_PERMISSION_DENIED';
 return {state:'RUN_UNVERIFIED',phase:safePhase,reason,reconcile_before_retry:true};
}
module.exports={classify};
