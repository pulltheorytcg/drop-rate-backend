import {describe,expect,it,vi} from "vitest";
import {
  createAuthorisedAuctionResolver,
  type PilotCardObservation, type PilotInput,
} from "../src/lib/auctionLensResolver";
import type {CaptureFrame} from "../src/lib/auctionLensStream";
import {HUB_ORIGIN} from "../src/lib/hub";

const OBS: PilotCardObservation = {
  game:"Pokemon",language:"English",name:"Rapidash",set_name:"Temporal Forces",
  card_number:"048/162",finish:"Normal",object_type:"RAW_CARD",
};
const FRAME: CaptureFrame = {
  capturedAtMs:500,fingerprint64:"1111111111111111",
  quality:"CLEAR",jpegDataUrl:"data:image/jpeg;base64,ZmFrZQ==",
};
const configured=(transport:typeof fetch,token:string|null="test-token",
                  input:PilotInput|null|undefined=undefined)=>
  createAuthorisedAuctionResolver({
    accessToken:async()=>token,
    currentInput:()=>input===undefined?{observed:OBS,source:"OWN_VIDEO"}:input,
    transport,
  });

describe("authenticated owned-video auction resolver",()=>{
  it("posts a cropped frame only to our exact backend and never leaks a token in URL",async()=>{
    const fn=vi.fn(async(_url:RequestInfo|URL,_opts?:RequestInit)=>new Response(JSON.stringify({
      generation:7,decision:"EXACT",identityKey:"card:abc:English:Normal:RAW",
      title:"Rapidash",
    }),{status:200,headers:{"Content-Type":"application/json"}}));
    const result=await configured(fn as typeof fetch)(FRAME,7,new AbortController().signal);
    expect(result.decision).toBe("EXACT");
    expect(result.value).toBeUndefined();
    expect(fn).toHaveBeenCalledTimes(1);
    const [url,options]=fn.mock.calls[0];
    expect(url).toBe(HUB_ORIGIN+"/api/v1/auction-lens/pilot/resolve");
    expect((options!.headers as Record<string,string>).Authorization).toBe("Bearer test-token");
    expect(options?.method).toBe("POST");
    expect(options?.credentials).toBe("omit");
    const body=JSON.parse(options!.body as string);
    expect(body.image_data_url).toBe(FRAME.jpegDataUrl);
    expect(body.source).toBe("OWN_VIDEO");
    expect(body.generation).toBe(7);
    expect(body.confirmed_raw_condition).toBeUndefined();
  });

  it("never contacts server without authentication, input, or fresh crop",async()=>{
    const fn=vi.fn(async()=>new Response("{}",{status:200}));
    expect((await configured(fn as typeof fetch,null)(FRAME,1,new AbortController().signal)).decision).toBe("CHECK_VERSION");
    expect((await configured(fn as typeof fetch,"token",null)(FRAME,1,new AbortController().signal)).decision).toBe("CHECK_VERSION");
    expect((await configured(fn as typeof fetch)({...FRAME,quality:"BLURRED"},1,new AbortController().signal)).decision).toBe("CHECK_VERSION");
    expect(fn).toHaveBeenCalledTimes(0);
  });

  it("rejects stale generations and invalid USD value",async()=>{
    const fn=vi.fn(async()=>new Response(JSON.stringify({
      generation:1,decision:"EXACT",identityKey:"card:abc:English:Normal:RAW",title:"Rapidash",
      value:{marketValueMinor:12000,currency:"USD",source:"unknown",expiresAtMs:Date.now()+10000,valuationEligible:true},
    }),{status:200}));
    const resolver=configured(fn as typeof fetch);
    expect((await resolver(FRAME,2,new AbortController().signal)).decision).toBe("CHECK_VERSION");
    const result=await resolver(FRAME,1,new AbortController().signal);
    expect(result.decision).toBe("EXACT");
    expect(result.value).toBeUndefined();
  });

  it("honors cancellation and disabled endpoints",async()=>{
    const fn=vi.fn(async()=>new Response("{}",{status:404}));
    const stopped=new AbortController();stopped.abort();
    const resolver=configured(fn as typeof fetch);
    expect((await resolver(FRAME,2,stopped.signal)).decision).toBe("CHECK_VERSION");
    expect(fn).toHaveBeenCalledTimes(0);
    expect((await resolver(FRAME,2,new AbortController().signal)).decision).toBe("CHECK_VERSION");
  });

  it("includes a condition only after explicit confirmation",async()=>{
    const fn=vi.fn(async(_url:RequestInfo|URL,_opts?:RequestInit)=>new Response(JSON.stringify({generation:3,decision:"CHECK_VERSION"}),{status:200}));
    await configured(fn as typeof fetch,"test",{
      observed:OBS,source:"EXPLICITLY_AUTHORISED_VIDEO",confirmed_raw_condition:"Near Mint",
    })(FRAME,3,new AbortController().signal);
    const body=JSON.parse(fn.mock.calls[0][1]!.body as string);
    expect(body.confirmed_raw_condition).toBe("Near Mint");
    expect(body.source).toBe("EXPLICITLY_AUTHORISED_VIDEO");
  });
});
