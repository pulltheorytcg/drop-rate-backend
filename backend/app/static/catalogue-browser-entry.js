"use strict";
(() => {
  const seller = Boolean(document.getElementById("owner-view-scan"));
  const scanner = () => seller ? ownerSharedScanner() : founderSharedScanner();
  const host = document.getElementById(seller ? "owner-view-search" : "seller-view-search");
  const navigate = view => seller ? activateOwnerView(view === "home" ? "overview" : view)
    : activateSellerView(view === "home" ? "dashboard" : view, true);
  if(!host)return;
  if(!seller)host.append(makeSellerHeading("Discover", "Search", "Explore every game, set and printing. Your collection starts here."));
  let opening=false;
  window.openDropRateCatalogue = async () => {
    if (!state.session?.access_token || opening) return;
    opening=true;
    try {
      navigate("search");
      if (!window.dropRateCatalogue || !window.dropRateCatalogue.active()) {
        window.dropRateCatalogue?.destroy();
        window.dropRateCatalogue = new window.DropRateCatalogue.Browser({host,client:scanner(),navigate,
          scan:async mode=>{if(seller)ownerScanStopCamera();else stopRecognitionCamera();await scanner().open(mode);},
          graded:async row=>{const current=scanner();await current.open("GRADED");current.manualSlab();
            if(row.catalogue_id&&current.edit){const candidate={...row,catalogue_id:row.catalogue_id,candidate_snapshot:row,market_value_minor:null,image_url:row.display_image_url};
              current.edit.item.candidates=[candidate];current.edit.selected=candidate;current.renderSlabDetails();}},
          afterSave:()=>seller?Promise.all([loadOwnerOverview(),loadOwnerInventory()]):reloadDashboard(),
        });
      }
      opening=false;
      await window.dropRateCatalogue.open();
    } finally {opening=false;}
  };
  const launch=()=>window.openDropRateCatalogue().catch(error=>{
    let status=host.querySelector('.catalogue-entry-error');
    if(!status){status=document.createElement('p');status.className='catalogue-entry-error';status.setAttribute('role','status');host.append(status);}
    status.textContent=error.message;
  });
  document.querySelectorAll('[data-browse-products]:not([data-owner-view])').forEach(control=>control.addEventListener('click',launch));
  const shortcut=document.createElement('button');shortcut.type='button';shortcut.className='dr-browse-launch';shortcut.textContent='Search cards & sets';shortcut.addEventListener('click',launch);
  document.getElementById(seller?'owner-view-scan':'recognition-scanner-panel')?.prepend(shortcut);
  document.addEventListener(seller?'owner-view-changed':'seller-view-changed',event=>{
    if(event.detail.view==='search')launch();
    else if(window.dropRateCatalogue?.embedded)window.dropRateCatalogue.close();
  });
  document.addEventListener('hub-ready',()=>{if(!host.classList.contains('hidden'))launch();});
  window.addEventListener('hub-session-cleared',()=>{window.dropRateCatalogue?.destroy();window.dropRateCatalogue=null;});
  if(seller){const nav=document.querySelector('.owner-nav');['overview','search','scan','inventory','more'].forEach(view=>{const item=nav.querySelector(`[data-owner-view="${view}"]`);if(item)nav.append(item);});}
  const workspace=document.getElementById(seller?"owner-portal-view":"dashboard-view");
  if(state.session?.access_token && workspace && !workspace.classList.contains("hidden") && !host.classList.contains("hidden"))launch();
})();
