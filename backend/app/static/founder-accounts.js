/* Business uses existing read-only founder APIs. Every request is roster-checked. */
"use strict";
(() => {
  if (typeof sellerView !== "function") return;
  const view = sellerView("accounts");
  if (!view) return;
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls = "") => { const el=document.createElement(tag); if(text!=null)el.textContent=String(text); if(cls)el.className=cls; return el; };
  const money = value => value==null ? "Not recorded" : new Intl.NumberFormat("en-GB",{style:"currency",currency:"GBP"}).format(Number(value)/100);
  const tabs = [["overview","Overview"],["sellers","Sellers"],["inventory","Stock ownership"],["activity","Sales & payouts"]];
  let generation=0, accounts=[], ownOwner=null, mode="overview", offset=0, allowed=false, actor=null;
  const limit=40;
  function setAllowed(value) {
    allowed=Boolean(value);
    document.querySelectorAll('[data-more-view="accounts"],.business-entry').forEach(b=>{b.hidden=!allowed;});
    $("business-content").hidden=!allowed;
  }
  function erase() {
    ++generation;accounts=[];ownOwner=null;actor=null;offset=0;setAllowed(false);
    $("accounts-summary").replaceChildren();$("accounts-results").replaceChildren();
    $("accounts-owner").replaceChildren(new Option("All active accounts",""));
    $("business-seller-search").value=$("accounts-search").value="";$("accounts-page").textContent="";
    $("accounts-prev").disabled=$("accounts-next").disabled=true;
  }
  function status(text,error=false) {$("accounts-message").textContent=text;$("accounts-message").classList.toggle("is-error",error);}
  function activate(tab) {
    mode=tabs.some(([key])=>key===tab)?tab:"overview";offset=0;
    document.querySelectorAll('[data-business-tab]').forEach(b=>{const active=b.dataset.businessTab===mode;b.setAttribute("aria-selected",String(active));b.tabIndex=active?0:-1;});
    $("business-panel").setAttribute("aria-labelledby",`business-tab-${mode}`);
    $("accounts-summary").hidden=mode!=="overview";$("business-seller-filters").hidden=mode!=="sellers";
    $("accounts-form").hidden=!["inventory","activity"].includes(mode);$("accounts-search-label").hidden=mode!=="inventory";
    $("accounts-pages").hidden=!["inventory","activity"].includes(mode);load();
  }
  async function access() {
    if(!state.session?.access_token){erase();status("Sign in with your founder account to open Business.");return false;}
    const who=state.session.user?.id;if(!who){erase();status("Please sign in again.");return false;}
    if(actor&&actor!==who)erase();
    const request=generation,result=await apiRequest("/api/v1/access/me");
    if(request!==generation||state.session?.user?.id!==who)return false;
    if(result.access?.business_allowed!==true){erase();status("Business is available only to the three verified founder accounts.",true);return false;}
    actor=who;setAllowed(true);return true;
  }
  async function refreshAccess(){try{await access();}catch(_error){erase();status("Business access could not be verified. Retry or sign in with your founder account.",true);}}
  const accountLabel=row=>`${row.display_name}${row.id===ownOwner?" (you)":""}`;
  function selectOwner(id){$("accounts-owner").value=id;$("accounts-search").value="";activate("inventory");}
  function overview(){
    const sum=key=>accounts.reduce((total,row)=>total+Number(row[key]||0),0),summary=$("accounts-summary");summary.replaceChildren();
    [["Active accounts",accounts.length,"Founders and consignors"],["Approved for sale",sum("for_sale_count"),"Physical copies, not product listings"],["Draft records",sum("draft_count"),"Not approved stock"],["Awaiting valuation",sum("unvalued_count"),"Active records with no market value"]].forEach(([label,value,hint])=>{const card=node("article",null,"business-kpi");card.append(node("span",label),node("strong",value),node("small",hint));summary.append(card);});
    const output=$("accounts-results");output.replaceChildren();
    const intro=node("section",null,"business-intro");intro.append(node("h2","Who owns what?"),node("p","Find a seller, inspect their stock, or look up a card across all active owners. Each copy keeps its existing Inventory ID."));
    const actions=node("div",null,"business-actions");[["Find a seller","sellers"],["Look up a product","inventory"]].forEach(([label,tab])=>{const b=node("button",label,"business-button");b.type="button";b.onclick=()=>activate(tab);actions.append(b);});intro.append(actions);output.append(intro);
    const tools=node("details",null,"business-tools");tools.append(node("summary","Existing founder tools"),node("p","Opens the existing tools without changing their permissions or moving stock. Financial tools retain their current owner scope."));
    const links=node("div",null,"business-actions");[["My inventory","inventory"],["Identity reviews","verification"],["Photos & condition","media"],["My sales","sales"],["My payouts","balance"],["Reports & settlements","reports"],["Settings & channels","settings"]].forEach(([label,target])=>{const b=node("button",label,"business-button secondary");b.type="button";b.onclick=()=>activateSellerView(target,true);links.append(b);});tools.append(links);output.append(tools);
  }
  function sellers(){
    const q=$("business-seller-search").value.trim().toLowerCase(),kind=$("business-owner-type").value;
    const visible=accounts.filter(row=>(!kind||row.owner_type===kind)&&[row.display_name,row.username,row.id].some(v=>String(v||"").toLowerCase().includes(q)));
    const output=$("accounts-results");output.replaceChildren();output.append(node("p",`${visible.length} active account${visible.length===1?"":"s"}`,"business-caption"));
    const grid=node("div",null,"business-seller-grid");visible.forEach(row=>{
      const card=node("article",null,"business-seller-card"),avatar=node("span",String(row.display_name||"?").slice(0,1),"business-avatar");avatar.setAttribute("aria-hidden","true");
      const title=node("div",null,"business-seller-title");title.append(avatar,node("h2",accountLabel(row)));card.append(title);
      card.append(node("p",[row.owner_type==="FOUNDER"?"Founder":"Consignor",row.username&&`@${row.username}`].filter(Boolean).join(" · "),"business-caption"),node("p",`${row.active_stock_count||0} active stock records · ${row.draft_count||0} Draft · ${row.for_sale_count||0} approved for sale`));
      const b=node("button","View products","business-button");b.type="button";b.setAttribute("aria-label",`View products owned by ${row.display_name}`);b.onclick=()=>selectOwner(row.id);card.append(b);grid.append(card);
    });
    if(!visible.length)grid.append(node("p","No active accounts match your search. Try the seller's name or username.","business-empty"));output.append(grid);
  }
  function table(title,headings,records){
    const section=node("section",null,"business-table-section");section.append(node("h2",title));if(!records.length){section.append(node("p","No records for this selection.","business-empty"));return section;}
    const wrap=node("div",null,"business-table-wrap"),grid=node("table",null,"business-table"),head=node("thead"),row=node("tr");headings.forEach(label=>{const th=node("th",label);th.scope="col";row.append(th);});head.append(row);
    const body=node("tbody");records.forEach(values=>{const tr=node("tr");values.forEach((value,index)=>{const td=node("td");td.dataset.label=headings[index];if(value instanceof HTMLElement)td.append(value);else td.textContent=String(value??"—");tr.append(td);});body.append(tr);});grid.append(head,body);wrap.append(grid);section.append(wrap);return section;
  }
  async function load(refreshAccounts=false){
    const request=++generation,who=state.session?.user?.id,current=()=>request===generation&&state.session?.access_token&&state.session?.user?.id===who;
    $("accounts-results").replaceChildren();$("accounts-summary").replaceChildren();$("accounts-prev").disabled=$("accounts-next").disabled=true;$("accounts-page").textContent="";status("Checking Business access…");
    try{
      if(!await access()||!current())return;status("Loading business records…");
      if(refreshAccounts||!accounts.length){const response=await apiRequest("/api/v1/founder/accounts");if(!current())return;if(!Array.isArray(response.accounts))throw new Error("Invalid account response");accounts=response.accounts;ownOwner=response.own_owner_id;
        const selected=$("accounts-owner").value;$("accounts-owner").replaceChildren(new Option("All active accounts",""));accounts.forEach(row=>$("accounts-owner").append(new Option(accountLabel(row),row.id)));$("accounts-owner").value=accounts.some(row=>row.id===selected)?selected:"";}
      if(mode==="overview")overview();else if(mode==="sellers")sellers();else{
        const params=new URLSearchParams({limit:String(limit),offset:String(offset)}),owner=$("accounts-owner").value;if(owner)params.set("owner_id",owner);if(mode==="inventory")params.set("search",$("accounts-search").value.trim());
        const response=await apiRequest(`/api/v1/founder/accounts/${mode}?${params}`);if(!current())return;const output=$("accounts-results");
        if(mode==="inventory"){
          output.append(table("Physical stock records",["Owner","Product / Inventory ID","Details","Status","Value / store price","Shopify"],(response.items||[]).map(item=>{
            const ownerButton=node("button",item.owner_name,"business-owner-link");ownerButton.type="button";ownerButton.onclick=()=>selectOwner(item.owner_id);
            const identity=node("div");identity.append(node("strong",item.name),node("small",[item.game,item.set_name,item.card_number].filter(Boolean).join(" · ")),node("code",item.inventory_code));
            const details=[item.language,item.grading_company&&item.grade?`${item.grading_company} ${item.grade}`:item.condition,item.variant,item.certificate_number&&`Cert ${item.certificate_number}`,item.location&&`Location: ${item.location}`].filter(Boolean).join(" · ");
            return [ownerButton,identity,details||"Details not recorded",`${item.status} · ${item.sale_intent==="PERSONAL_COLLECTION"?"Personal collection":"For sale intent"}`,`${money(item.market_value_minor)} / ${money(item.store_price_minor)}`,item.shopify_state||"No recorded link"];
          })));
          const total=Number(response.total||0);$("accounts-next").disabled=offset+limit>=total;$("accounts-page").textContent=total?`${offset+1}–${Math.min(offset+limit,total)} of ${total} records`:"0 records";
        }else{
          const sales=response.sales||[],payouts=response.payouts||[];
          output.append(table("Recorded sale allocations",["Owner","Order","Channel","Order status","Item price"],sales.map(row=>[row.owner_name,row.order_number,row.source,row.status,money(row.sale_price_minor)])),table("Payout requests",["Owner","Request","Status","Amount"],payouts.map(row=>[row.owner_name,row.payout_code,row.status,money(row.amount_minor)])));
          $("accounts-next").disabled=sales.length<limit&&payouts.length<limit;$("accounts-page").textContent=`Page ${Math.floor(offset/limit)+1} · recorded history, newest first`;
        }
        $("accounts-prev").disabled=offset===0;
      }
      status("Read-only business view · Active owner accounts · "+new Date().toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit"}));
    }catch(error){if(!current())return;if([401,403,409].includes(error.status)){erase();status("Business access is no longer available. Sign in with an authorised founder account.",true);}else{$("accounts-results").replaceChildren();$("accounts-summary").replaceChildren();status("Business records could not load. Use Refresh to retry; no stock was changed.",true);}}
  }
  function init(){
    view.classList.add("business-area");view.setAttribute("aria-label","Business");if(!$("business-styles")){const link=node("link");link.id="business-styles";link.rel="stylesheet";link.href="/assets/business-area.css?v=1";document.head.append(link);}
    const heading=node("header",null,"business-heading"),copy=node("div");copy.append(node("p","DROP RATE · FOUNDERS ONLY","business-kicker"),node("h1","Business"),node("p","Company oversight, without the clutter. Your stock and every seller's ownership stay separate."));
    const refresh=node("button","Refresh","business-button secondary");refresh.id="business-refresh";refresh.type="button";refresh.onclick=()=>load(true);heading.append(copy,refresh);view.append(heading);
    const message=node("p","Sign in with your founder account to open Business.","business-message");message.id="accounts-message";message.setAttribute("role","status");view.append(message);
    const content=node("div");content.id="business-content";content.hidden=true;const nav=node("div",null,"business-tabs");nav.setAttribute("role","tablist");nav.setAttribute("aria-label","Business views");
    tabs.forEach(([key,label],index)=>{const b=node("button",label);b.id=`business-tab-${key}`;b.type="button";b.dataset.businessTab=key;b.setAttribute("role","tab");b.setAttribute("aria-controls","business-panel");b.setAttribute("aria-selected",String(index===0));b.tabIndex=index===0?0:-1;b.onclick=()=>activate(key);nav.append(b);});
    nav.addEventListener("keydown",event=>{const buttons=[...nav.querySelectorAll('button')],i=buttons.indexOf(event.target);if(i<0)return;let j;if(event.key==="ArrowRight")j=(i+1)%buttons.length;if(event.key==="ArrowLeft")j=(i+buttons.length-1)%buttons.length;if(event.key==="Home")j=0;if(event.key==="End")j=buttons.length-1;if(j===undefined)return;event.preventDefault();buttons[j].focus();buttons[j].click();});content.append(nav);
    const panel=node("div");panel.id="business-panel";panel.setAttribute("role","tabpanel");panel.setAttribute("aria-labelledby","business-tab-overview");const summary=node("div",null,"business-kpis");summary.id="accounts-summary";panel.append(summary);
    const sellerFilters=node("div",null,"business-filters");sellerFilters.id="business-seller-filters";sellerFilters.hidden=true;sellerFilters.innerHTML='<label>Find an account<input id="business-seller-search" type="search" maxlength="160" placeholder="Seller name, username or account ID"></label><label>Account type<select id="business-owner-type"><option value="">All active accounts</option><option value="CONSIGNOR">Consignors</option><option value="FOUNDER">Founders</option></select></label>';
    for(const event of ["input","change"])sellerFilters.addEventListener(event,()=>{if(allowed&&mode==="sellers")sellers();});panel.append(sellerFilters);
    const form=node("form",null,"business-filters");form.id="accounts-form";form.hidden=true;form.innerHTML='<label>Owner<select id="accounts-owner"><option value="">All active accounts</option></select></label><label id="accounts-search-label">Find a product<input id="accounts-search" type="search" maxlength="160" placeholder="Card, set, number, Inventory ID or owner"></label><button type="submit" class="business-button">Search</button>';
    form.onsubmit=event=>{event.preventDefault();offset=0;load();};form.querySelector("select").onchange=()=>{offset=0;load();};panel.append(form);
    const output=node("div");output.id="accounts-results";panel.append(output);const pages=node("div",null,"business-pages");pages.id="accounts-pages";pages.hidden=true;pages.innerHTML='<button id="accounts-prev" type="button" class="business-button secondary" disabled>Previous</button><span id="accounts-page" aria-live="polite"></span><button id="accounts-next" type="button" class="business-button secondary" disabled>Next</button>';panel.append(pages);
    content.append(panel,node("p","Stock counts are records, not a reconciled collection valuation. Draft imports may overlap existing stock until reviewed. This view never merges, publishes or changes ownership.","business-notice"));view.append(content);
    $("accounts-prev").onclick=()=>{offset=Math.max(0,offset-limit);load();};$("accounts-next").onclick=()=>{offset+=limit;load();};
    const topbar=document.querySelector('#dashboard-view .topbar-actions');if(topbar){const entry=node("button","Business","business-entry");entry.type="button";entry.hidden=true;entry.onclick=()=>activateSellerView("accounts",true);topbar.prepend(entry);}setAllowed(false);
  }
  init();document.addEventListener("hub-ready",refreshAccess);document.addEventListener("seller-view-changed",event=>{if(event.detail.view==="accounts")load(true);});
  window.addEventListener("hub-session-cleared",()=>{erase();status("Sign in with your founder account to open Business.");});window.addEventListener("pagehide",()=>erase());window.addEventListener("pageshow",event=>{if(event.persisted){refreshAccess();if(!view.classList.contains("hidden"))load(true);}});
  const previousReload=reloadDashboard;reloadDashboard=async function(...args){const result=await previousReload(...args);await refreshAccess();if(allowed&&!view.classList.contains("hidden"))await load(true);return result;};
})();
