"use strict";
(() => {
  const seller = Boolean(document.getElementById("owner-view-scan"));
  const scanner = () => seller ? ownerSharedScanner() : founderSharedScanner();
  const navigate = view => seller ? activateOwnerView(view === "home" ? "overview" : view)
    : activateSellerView(view === "home" ? "dashboard" : view, true);
  window.openDropRateCatalogue = async () => {
    if (!state.session?.access_token) return;
    if (!window.dropRateCatalogue || window.dropRateCatalogue.destroyed || !window.dropRateCatalogue.active()) {
      window.dropRateCatalogue?.destroy();
      window.dropRateCatalogue = new window.DropRateCatalogue.Browser({client:scanner(), navigate,
        scan:async mode=>{if(seller)ownerScanStopCamera();else stopRecognitionCamera();await scanner().open(mode);},
        graded:async row=>{
          const current=scanner();await current.open("GRADED");current.manualSlab();
          if(row.catalogue_id && current.edit){const candidate={...row,catalogue_id:row.catalogue_id,candidate_snapshot:row,market_value_minor:null,image_url:row.display_image_url};
            current.edit.item.candidates=[candidate];current.edit.selected=candidate;current.renderSlabDetails();}
        },
        afterSave:()=>seller?Promise.all([loadOwnerOverview(),loadOwnerInventory()]):reloadDashboard(),
      });
    }
    await window.dropRateCatalogue.open();
  };
  const launch = () => window.openDropRateCatalogue().catch(error=>{
    if(seller)ownerScanMessage(error.message,"error");else showMessage("recognition-message",error.message,"error");
  });
  document.querySelectorAll('[data-browse-products]').forEach(control=>control.addEventListener("click",launch));
  const scanHost=document.getElementById(seller?"owner-view-scan":"recognition-scanner-panel");
  const shortcut=document.createElement("button");shortcut.type="button";shortcut.className="dr-browse-launch";shortcut.textContent="⌕ Search products & sets";shortcut.addEventListener("click",launch);
  scanHost?.prepend(shortcut);
  if(!seller){
    const search=sellerView("search");
    if(search){search.append(makeSellerHeading("Drop Rate catalogue","Search products","Browse games, sets and exact printings."));
      const open=shortcut.cloneNode(true);open.addEventListener("click",launch);search.append(open);}
    document.addEventListener("seller-view-changed",event=>{if(event.detail.view==="search")launch();});
  } else {
    const search=document.querySelector('.owner-nav-item[data-browse-products]');
    const inventory=document.querySelector('.owner-nav-item[data-owner-view="inventory"]');
    if(search&&inventory)inventory.before(search);
    const scan=document.querySelector('.owner-nav-item[data-owner-view="scan"]');
    if(scan&&inventory)inventory.before(scan);
  }
})();
