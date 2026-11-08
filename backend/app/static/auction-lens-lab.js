/* Auction Lens Lab: local/explicitly permitted video ONLY. No live URL capture.
 * No audio, video upload, background recording, permanent frame storage or bids.
 * All values come from a server-verified, owner-authenticated, opt-in route.
 */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const video = $("footage"), canvas = $("card-canvas"), hashCanvas = $("hash-canvas");
  const context = canvas.getContext("2d", {willReadFrequently:true});
  const hashContext = hashCanvas.getContext("2d", {willReadFrequently:true});
  const controls = ["crop-left","crop-top","crop-width","crop-height"];
  let objectURL = null, interval = null, currentRequest = null, generation = 0;
  let anchor = null, stable = 0, attempted = false, lastSample = -Infinity;
  let running = false, previousVideoTime = -1;
  let betaAllowed = false, betaCheckId = 0, betaCheckInterval = null;

  let bidObservedAtMs = 0, bannerEvidenceExpiresAt = 0, bannerBidExpiresAt = 0;
  const pounds = new Intl.NumberFormat("en-GB",{style:"currency",currency:"GBP"});
  const money = minor => pounds.format(minor / 100);

  function parsePence(inputId) {
    const value = $(inputId).value.trim();
    if (!value) return null; // Explicitly unknown; never imply £0.
    if (!/^\d{1,7}(?:\.\d{1,2})?$/.test(value)) {
      throw new Error("Use pounds with at most two decimal places.");
    }
    const parts = value.split(".");
    const pennies = Number(parts[0]) * 100 + Number((parts[1] || "").padEnd(2,"0"));
    if (!Number.isSafeInteger(pennies) || pennies > 100_000_000) {
      throw new Error("Auction amount is outside the permitted range.");
    }
    return pennies;
  }

  function observedQuote() {
    const bid = parsePence("bid-manual");
    if (bid === null) return null;
    return {
      lot_ref:"own-video-"+generation,
      status:"ACTIVE", currency:"GBP", bid_minor:bid,
      shipping_minor:parsePence("ship-manual"),
      buyer_fees_minor:parsePence("fee-manual"),
      import_tax_minor:parsePence("tax-manual"),
      additional_costs_minor:parsePence("other-manual"),
      bid_observed_at:new Date(bidObservedAtMs || 0).toISOString(),
    };
  }

  function resetBanner(label) {
    bannerEvidenceExpiresAt=0; bannerBidExpiresAt=0;
    const banner=$("auction-banner"),thumb=$("auction-banner-thumb");
    banner.hidden=!running;
    thumb.hidden=true; thumb.removeAttribute("src");
    $("auction-banner-title").textContent=label||"Scanning for a card…";
    $("auction-banner-subtitle").textContent="Verifying exact printing and UK market evidence";
    for(const id of ["auction-banner-bid","auction-banner-all-in","auction-banner-market"])$(id).textContent="—";
    $("auction-banner-verdict").dataset.state="WAITING";
    $("auction-banner-verdict").textContent="CHECKING";
  }

  function updateBanner(result, localFrame, quote) {
    // Called ONLY for the current active generation and a server EXACT result.
    const value=result.value,comparison=result.comparison;
    const verified=Boolean(value&&value.currency==="GBP"&&value.valuationEligible===true
      && Number.isSafeInteger(value.marketValueMinor)&&value.marketValueMinor>0
      && typeof value.expiresAtMs==="number"&&Date.now()<value.expiresAtMs&&value.source);
    $("auction-banner").hidden=false;
    $("auction-banner-thumb").src=localFrame;
    $("auction-banner-thumb").hidden=false;
    $("auction-banner-title").textContent=result.title;
    $("auction-banner-subtitle").textContent=verified
      ? "Exact printing · eligible UK sold evidence" : "Exact printing · Market Value unavailable";
    if(quote)$("auction-banner-bid").textContent=money(quote.bid_minor);
    $("auction-banner-market").textContent=verified?money(value.marketValueMinor):"—";
    bannerEvidenceExpiresAt=verified?value.expiresAtMs:0;
    const badge=$("auction-banner-verdict");
    badge.dataset.state="WAITING";badge.textContent=verified?"VALUE CHECKED":"NO CURRENT VALUE";
    // Do not compute a client-side bargain from an asking price or from partial fees.
    const status=comparison&&comparison.status;
    const complete=verified&&quote&&
      ["UNDER_MARKET","OVER_MARKET","AROUND_MARKET"].includes(status)&&
      Number.isSafeInteger(comparison.allInMinor)&&comparison.allInMinor>=0&&
      comparison.marketValueMinor===value.marketValueMinor&&
      Number.isSafeInteger(comparison.differenceMinor)&&
      comparison.differenceMinor===value.marketValueMinor-comparison.allInMinor&&
      Number.isFinite(comparison.bidExpiresAtMs)&&comparison.bidExpiresAtMs>Date.now();
    if(complete) {
      // Bid observations age out independently of market evidence. A static
      // frame must never keep a "BELOW MARKET" label after the bid goes stale.
      bannerBidExpiresAt=comparison.bidExpiresAtMs;
      $("auction-banner-all-in").textContent=money(comparison.allInMinor);
      badge.dataset.state=status;
      badge.textContent=status==="UNDER_MARKET"?"↓ "+money(comparison.differenceMinor)+" BELOW"
        :status==="OVER_MARKET"?"↑ "+money(-comparison.differenceMinor)+" ABOVE"
        :"AROUND MARKET";
    } else if(status==="CHARGES_UNKNOWN") {
      badge.textContent="FEES UNKNOWN";
    } else if(status==="STALE_BID") {
      badge.textContent="BID TOO OLD";
    } else if(status==="CHECK_VERSION") {
      badge.textContent="CHECK VERSION";
    }
  }


  function show(status, title, explanation, price, latency) {
    $("result-state").textContent = status;
    $("result-title").textContent = title || "Waiting for a clear card";
    $("result-explanation").textContent = explanation || "No current UK sold-market evidence has been confirmed.";
    $("result-price").textContent = price || "—";
    $("result-latency").textContent = latency || "";
    $("result-light").classList.toggle("active", running);
  }

  function invalidate(label) {
    generation++;
    if (currentRequest) { currentRequest.abort(); currentRequest = null; }
    anchor = null; stable = 0; attempted = false; lastSample = -Infinity;
    previousVideoTime = -1;
    show(label || "Checking", "Waiting for a stable card", "Old cards and values are cleared whenever a scene or crop changes.");
    resetBanner(label || "Scanning for a card…");
  }

  function coords() {
    const left = Number($("crop-left").value), top = Number($("crop-top").value);
    const width = Math.min(Number($("crop-width").value), 100-left);
    const height = Math.min(Number($("crop-height").value), 100-top);
    return {x:left/100,y:top/100,width:width/100,height:height/100};
  }

  function drawCrop() {
    if (!context || !video.videoWidth || !video.videoHeight) return false;
    const crop = coords();
    const sx = Math.round(video.videoWidth * crop.x);
    const sy = Math.round(video.videoHeight * crop.y);
    const sw = Math.round(video.videoWidth * crop.width);
    const sh = Math.round(video.videoHeight * crop.height);
    if (sw < 200 || sh < 200) {
      show("Adjust crop", "Card region is too small", "Increase width or height until the region has at least 200 pixels on both axes.");
      return false;
    }
    const scale = Math.min(1, 520/Math.max(sw,sh));
    canvas.width = Math.round(sw*scale);
    canvas.height = Math.round(sh*scale);
    if (canvas.width < 200 || canvas.height < 200) return false;
    context.clearRect(0,0,canvas.width,canvas.height);
    context.drawImage(video,sx,sy,sw,sh,0,0,canvas.width,canvas.height);
    return true;
  }

  function differenceHash() {
    if (!hashContext) return null;
    hashContext.drawImage(canvas,0,0,9,8);
    const data = hashContext.getImageData(0,0,9,8).data;
    let minimum=255, maximum=0, bits=0n;
    const gray = [];
    for(let i=0;i<72;i++) {
      const offset=i*4;
      const v=Math.round(data[offset]*0.299+data[offset+1]*0.587+data[offset+2]*0.114);
      gray.push(v); minimum=Math.min(minimum,v); maximum=Math.max(maximum,v);
    }
    if(maximum-minimum<12) return null;
    for(let y=0;y<8;y++) for(let x=0;x<8;x++) {
      bits<<=1n;
      if(gray[y*9+x]>gray[y*9+x+1])bits|=1n;
    }
    return bits.toString(16).padStart(16,"0");
  }

  function distance(a,b) {
    let v=BigInt("0x"+a)^BigInt("0x"+b), count=0;
    while(v){v&=v-1n;count++;}
    return count;
  }

  function accessToken() {
    const session=window.PullTheoryHubSession?.read?.();
    return session && typeof session.access_token==="string" ? session.access_token : null;
  }

  function applyBetaAccess(allowed, message) {
    const previouslyAllowed=betaAllowed;
    betaAllowed=allowed;
    $("video-file").disabled=!allowed;
    $("start-scan").disabled=!allowed;
    $("new-lot").disabled=!allowed;
    $("beta-access-state").textContent=message;
    $("beta-access-state").dataset.access=allowed?"granted":"denied";
    if(previouslyAllowed&&!allowed)stop();
  }

  async function checkBetaAccess() {
    const id=++betaCheckId;
    const token=accessToken();
    if(!token) {
      applyBetaAccess(false,"Private beta · Sign in to Drop Rate to check access.");
      return;
    }
    try {
      const response=await fetch("/api/v1/auction-lens/pilot/access",{
        method:"GET",credentials:"omit",cache:"no-store",
        headers:{"Authorization":"Bearer "+token},
      });
      if(id!==betaCheckId)return; // No older response may re-grant access.
      if(!response.ok) {
        applyBetaAccess(false,"Private beta · This account is not approved or access has been disabled.");
        return;
      }
      const data=await response.json();
      if(id!==betaCheckId)return;
      if(data.enabled===true && data.footage_scope==="OWN_OR_EXPLICITLY_AUTHORISED_VIDEO") {
        applyBetaAccess(true,"Private beta enabled for this account · Authorised footage only.");
      } else {
        applyBetaAccess(false,"Private beta · Account entitlement could not be verified.");
      }
    } catch {
      if(id===betaCheckId) {
        applyBetaAccess(false,"Private beta · Connection unavailable. Access is paused.");
      }
    }
  }

  function identity() {
    return {
      game:"Pokemon", language:"English", object_type:"RAW_CARD",
      name:$("card-name").value.trim(), set_name:$("set-name").value.trim(),
      card_number:$("card-number").value.trim(), finish:$("finish").value,
    };
  }

  async function requestMatch(frameURL) {
    if(!betaAllowed){show("Private beta","Access has not been verified","Only approved Drop Rate accounts may use the recognition API.");return;}
    const token=accessToken(), observed=identity();
    if(!token){show("Sign in", "An active Drop Rate account is required", "Sign in through /app in this browser tab before using the pilot.");return;}
    if(!observed.name||!observed.set_name||!observed.card_number){
      show("Check details", "Confirm the visible printing", "Name, set and collector number are required for an exact result.");return;
    }
    let quote=null;
    try { quote=observedQuote(); }
    catch(error) {
      show("Check amounts", "Enter valid GBP amounts", "Each charge must be in pounds with no more than two decimal places.");
      resetBanner("Invalid auction amount");
      return;
    }
    const ownGeneration=generation, controller=new AbortController(), start=performance.now();
    currentRequest=controller; attempted=true;
    show("Recognising", "Matching exact artwork and printing", "One bounded internal lookup. No web scraping or external provider calls.");
    try{
      const response=await fetch("/api/v1/auction-lens/pilot/resolve",{
        method:"POST", credentials:"omit", cache:"no-store", signal:controller.signal,
        headers:{"Content-Type":"application/json","Authorization":"Bearer "+token},
        body:JSON.stringify({
          generation:ownGeneration, source:$("source-rights").value,
          image_data_url:frameURL, observed,
          ...( $("nm-confirmed").checked ? {confirmed_raw_condition:"Near Mint"} : {} ),
          ...(quote ? {quote} : {}),
        }),
      });
      if(controller.signal.aborted||ownGeneration!==generation||!running)return;
      const latency=Math.round(performance.now()-start)+" ms";
      if(response.status===404){show("Disabled", "Pilot is not activated", "The server feature is intentionally disabled until a founder-authorised test deployment.",null,latency);return;}
      if(!response.ok){show("Unavailable", "Check your login, crop or test permissions", "This test never retries or contacts auction platforms automatically.",null,latency);return;}
      const result=await response.json();
      if(controller.signal.aborted||ownGeneration!==generation||!running)return;
      if(result.generation!==ownGeneration||result.decision!=="EXACT"||!result.identityKey||!result.title){
        resetBanner("Check card version");
        show("Check version", "No safely verified exact printing", "Adjust the crop or visible details, then choose New lot. Similar artwork must not borrow another card's price.",null,latency);return;
      }
      const price=result.value;
      if(price && price.currency==="GBP" && price.valuationEligible===true
          && Number.isSafeInteger(price.marketValueMinor) && price.marketValueMinor>0
          && Date.now()<price.expiresAtMs && price.source) {
        const formatted=new Intl.NumberFormat("en-GB",{style:"currency",currency:"GBP"}).format(price.marketValueMinor/100);
        const checked=Number.isFinite(price.evidenceAtMs)
          ? new Intl.DateTimeFormat("en-GB",{timeZone:"Europe/London",dateStyle:"medium"}).format(new Date(price.evidenceAtMs))
          : "date unavailable";
        show("Exact match",result.title,"UK Market Value · "+(price.basis||"confirmed raw condition")+
          " · evidence "+checked+" · "+price.source,formatted,latency);
        updateBanner(result,frameURL,quote);
      } else {
        show("Identity found",result.title,"No eligible current UK Market Value for this exact printing and confirmed condition. Missing evidence remains unavailable.",null,latency);
        updateBanner(result,frameURL,quote);
      }
    }catch(error){
      if(!controller.signal.aborted&&ownGeneration===generation) {
        show("Unavailable", "Recognition request was interrupted", "No price is displayed without complete source verification.");
      }
    }finally{
      if(currentRequest===controller)currentRequest=null;
    }
  }

  function tick() {
    if(!running||!video.videoWidth||video.paused||video.ended)return;
    if(bannerEvidenceExpiresAt && Date.now()>=bannerEvidenceExpiresAt) {
      invalidate("Market evidence expired");
    }
    if(bannerBidExpiresAt && Date.now()>=bannerBidExpiresAt) {
      bannerBidExpiresAt=0;
      $("auction-banner-bid").textContent="—";
      $("auction-banner-all-in").textContent="—";
      $("auction-banner-verdict").dataset.state="WAITING";
      $("auction-banner-verdict").textContent="BID TOO OLD";
    }
    const now=performance.now();
    if(now-lastSample<250||previousVideoTime===video.currentTime)return;
    lastSample=now;previousVideoTime=video.currentTime;
    if(!drawCrop())return;
    const hash=differenceHash();
    if(!hash){invalidate("Protected/blank frame");return;}
    if(anchor!==null&&distance(anchor,hash)>6){
      invalidate("Scene changed");
    }
    if(anchor===null){anchor=hash;stable=1;}else stable++;
    if(stable<3||attempted||currentRequest)return;
    const frameURL=canvas.toDataURL("image/jpeg",.72);
    $("crop-preview").src=frameURL;
    void requestMatch(frameURL);
  }

  function stop() {
    running=false;
    if(interval){clearInterval(interval);interval=null;}
    if(!video.paused)video.pause();
    invalidate("Stopped");
    show("Stopped","Video recognition is off","No further frames are sent. Starting again requires explicit user action.");
  }

  $("video-file").addEventListener("change", event=>{
    if(!betaAllowed) {
      show("Private beta","Access is restricted","Sign in with an approved test account.");
      return;
    }
    stop();
    if(objectURL){URL.revokeObjectURL(objectURL);objectURL=null;}
    const file=event.target.files?.[0];
    if(!file)return;
    if(!file.type.startsWith("video/")){show("Unsupported","Choose a local video file");return;}
    objectURL=URL.createObjectURL(file);video.src=objectURL;video.load();
    $("video-empty").textContent="";$("video-frame").classList.add("loaded");
    show("Ready","Video loaded locally","Confirm the product crop and visible printing before starting.");
  });

  $("start-scan").addEventListener("click",async()=>{
    if(!betaAllowed){show("Private beta","Access is restricted","Use an approved test account.");return;}
    if(!$("rights-affirmed").checked){show("Permission required","Only use footage you are authorised to process");return;}
    if(!video.videoWidth){show("Choose video","Load a local video first");return;}
    if(!$("identity-form").reportValidity())return;
    if(!accessToken()){show("Sign in","An active Drop Rate login is required","Return to /app and sign in on this tab.");return;}
    if(running)return;
    running=true;invalidate("Watching");
    try{await video.play();}catch{show("Press play","Your browser needs you to start the video");}
    interval=setInterval(tick,250);
  });
  $("new-lot").addEventListener("click",()=>{invalidate("New lot"); if(running)tick();});
  $("stop-scan").addEventListener("click",stop);
  video.addEventListener("seeking",()=>{if(running)invalidate("Seeking");});
  video.addEventListener("ended",stop);
  video.addEventListener("pause",()=>{if(running)invalidate("Paused footage");});
  for(const id of ["bid-manual","ship-manual","fee-manual","tax-manual","other-manual"]) {
    $(id).addEventListener("input",()=>{
      bidObservedAtMs=Date.now();
      if(running)invalidate("Bid or fees changed");
    });
  }
  for(const id of ["card-name","set-name","card-number","finish","nm-confirmed"]) {
    $(id).addEventListener("change",()=>{ if(running)invalidate("Printing updated"); });
  }
  $("source-rights").addEventListener("change",()=>{if(running)invalidate("Footage source changed");});
  $("rights-affirmed").addEventListener("change",()=>{
    if(!$("rights-affirmed").checked&&running)stop();
  });

  controls.forEach(id=>{
    const input=$(id),output=$(id+"-value");
    input.addEventListener("input",()=>{
      output.textContent=input.value+"%";
      if(running)invalidate("Crop updated");
      if(video.videoWidth&&drawCrop())$("crop-preview").src=canvas.toDataURL("image/jpeg",.6);
    });
  });
  // Revocation is enforced by the server on every request; refresh local
  // entitlement as well so a running video stops shortly after access removal.
  void checkBetaAccess();
  betaCheckInterval=setInterval(()=>{void checkBetaAccess();},15000);
  window.addEventListener("pagehide",()=>{
    ++betaCheckId;
    if(betaCheckInterval)clearInterval(betaCheckInterval);
    stop();
    if(objectURL)URL.revokeObjectURL(objectURL);
    $("crop-preview").removeAttribute("src");
  });
})();
