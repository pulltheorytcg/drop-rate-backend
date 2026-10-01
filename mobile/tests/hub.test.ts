import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { HUB_ENTRY, isHubUrl, isExternalHttps } from '../src/lib/hub';
describe('existing hub navigation', () => {
  it('keeps both hubs on the exact trusted origin', () => {
    expect(isHubUrl(HUB_ENTRY)).toBe(true);
    expect(isHubUrl(new URL('/',HUB_ENTRY).href)).toBe(true);
    for (const url of ['http://drop-rate-api-live-production.up.railway.app/', 'https://drop-rate-api-live-production.up.railway.app.evil.test/', 'https://user@drop-rate-api-live-production.up.railway.app/', 'javascript:alert(1)', 'file:///etc/passwd']) expect(isHubUrl(url)).toBe(false);
    expect(isExternalHttps('https://example.com')).toBe(true);
    expect(isExternalHttps('intent://scan')).toBe(false);
  });
});
describe('shared hub session', () => {
  function fixture() {
    const store = new Map<string,string>();
    const window = {} as {PullTheoryHubSession: {read:()=> {access_token?:string;refresh_token?:string}|null;save:(session:object)=>void;clear:()=>void}};
    runInNewContext(readFileSync('../backend/app/static/hub-session.js','utf8'), {
      window, sessionStorage: {getItem: (key: string) => store.get(key) ?? null, setItem:(key: string,value:string) => store.set(key,value), removeItem:(key:string)=>store.delete(key)},
    });
    return {store, session:window.PullTheoryHubSession};
  }
  it('shares refreshed data and clears every hub on sign-out', () => {
    const {session,store}=fixture();
    session.save({access_token:'first',refresh_token:'first-refresh'});
    expect(session.read()?.access_token).toBe('first');
    session.save({access_token:'second',refresh_token:'second-refresh'});
    expect(session.read()?.refresh_token).toBe('second-refresh');
    store.set('drop_rate_founder_session','stale');
    store.set('drop_rate_owner_session','stale');
    session.clear();
    expect(session.read()).toBe(null);
    expect(store.size).toBe(0);
  });
  it('does not select a legacy account or retain malformed state', () => {
    const {session,store}=fixture();
    store.set('drop_rate_owner_session',JSON.stringify({user:{id:'seller'}}));
    store.set('drop_rate_founder_session',JSON.stringify({user:{id:'founder'}}));
    expect(session.read()).toBe(null);
    store.set('drop_rate_hub_session','invalid-json');
    expect(session.read()).toBe(null);
    expect(store.size).toBe(0);
  });
});

describe('existing hub role boundaries', () => {
  async function enter(file: string, functionName: string, access: object) {
    const source = readFileSync(`../backend/app/static/${file}`,'utf8');
    const start = source.indexOf(`async function ${functionName}()`);
    const end = source.indexOf('\nasync function ', start + 1);
    const script = source.slice(start,end);
    const calls: string[] = [];
    const redirects: string[] = [];
    let cleared = false;
    const context = {
      window: {location:{replace:(url:string)=>redirects.push(url)},locationHash:''},
      apiRequest: async (path:string) => { calls.push(path); return path.endsWith('/access/me') ? {access} : {owner:{display_name:'Test'}}; },
      state:{session:{user:{email:'test@example.invalid'}}},
      byId:()=>({classList:{add:()=>{},remove:()=>{}},value:''}),
      reloadDashboard: async()=>{}, reloadOwnerDashboard:async()=>{},
      activateOwnerView:()=>{},showOwnerOnboardingWelcome:()=>{},
      clearSession:()=>{cleared=true;},showForm:()=>{},showMessage:()=>{},
    };
    await runInNewContext(`${script}\n${functionName}()`,context);
    return {calls,redirects,cleared};
  }
  it('routes a verified seller away before any founder data loads',async()=>{
    const result=await enter('app.js','openDashboard',{access_role:'OWNER',portal:'OWNER_PORTAL',founder_hq_allowed:false});
    expect(result.redirects).toEqual(['/owner']);
    expect(result.calls).toEqual(['/api/v1/access/me']);
    expect(result.cleared).toBe(false);
  });
  it('denies an unprivileged account at the founder entry',async()=>{
    const result=await enter('app.js','openDashboard',{});
    expect(result.calls).toEqual(['/api/v1/access/me']);
    expect(result.cleared).toBe(true);
  });
  it('hands an authorized founder to the existing founder hub',async()=>{
    const result=await enter('owner-portal.js','openOwnerPortal',{access_role:'PLATFORM_ADMIN',founder_hq_allowed:true});
    expect(result.redirects).toEqual(['/']);
    expect(result.calls).toEqual(['/api/v1/access/me']);
    expect(result.cleared).toBe(false);
  });
});
