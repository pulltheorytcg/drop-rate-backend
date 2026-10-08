/* Shared presentation only. Each hub keeps its existing permission-scoped handlers. */
"use strict";
(() => {
  const seller=Boolean(document.getElementById('owner-view-more'));
  const navigate=view=>seller?activateOwnerView(view):activateSellerView(view,true);
  const tools={
    verification:['Review cards','Confirm identities and prepare your stock','✓'],
    media:['Photos & condition','Check artwork, photos and physical condition','▧'],
    sales:['Sales','Orders, fees and owner proceeds','↗'],
    balance:['Payouts','Balances, payout history and schedules','£'],
    settlements:['Settlements','Order allocations and reconciliation','≋'],
    reports:['Reports','Track performance and inventory value','▥'],
    channels:['Sales channels','Shopify, eBay and channel status','⇄'],
    settings:[seller?'Settings':'Settings & channels',seller?'Appearance and workspace settings':'Appearance, store connections and workspace settings','⚙'],
    accounts:['Accounts','Founder oversight of inventory and balances','◎'],
    profile:['Your account','Profile, contact details and sign-in settings','○']
  };
  const groups=[['Selling & payouts',['sales','balance','channels','settlements']],['Collection tools',['verification','media','reports']],['Workspace',['accounts','settings','profile']]];
  const more=document.getElementById(seller?'owner-view-more':'seller-view-more');
  const old=more?.querySelector('.app-more-grid');
  if(old){
    const buttons=new Map([...old.querySelectorAll('button')].map(b=>[seller?b.dataset.ownerJump:b.dataset.moreView,b]));
    for(const [title,keys] of groups){
      const existing=keys.filter(key=>buttons.has(key));if(!existing.length)continue;
      const section=document.createElement('section');section.className='workspace-tool-group';
      const heading=document.createElement('h2');heading.textContent=title;section.append(heading);
      const grid=document.createElement('div');grid.className='workspace-tool-grid';
      for(const key of existing){const b=buttons.get(key),[label,description,icon]=tools[key];b.replaceChildren();
        const symbol=document.createElement('span');symbol.className='workspace-tool-icon';symbol.textContent=icon;symbol.setAttribute('aria-hidden','true');
        const copy=document.createElement('span'),strong=document.createElement('strong'),small=document.createElement('small');strong.textContent=label;small.textContent=description;copy.append(strong,small);
        const arrow=document.createElement('span');arrow.textContent='›';arrow.setAttribute('aria-hidden','true');b.append(symbol,copy,arrow);grid.append(b);}
      section.append(grid);more.append(section);
    }
    old.remove();
  }
  const panels=seller?[...document.querySelectorAll('[data-owner-view-panel]')]:[...document.querySelectorAll('[data-seller-view]')];
  for(const panel of panels){const key=seller?panel.dataset.ownerViewPanel:panel.dataset.sellerView;if(!tools[key])continue;
    const back=document.createElement('button');back.type='button';back.className='workspace-back';back.textContent='← More';back.addEventListener('click',()=>navigate('more'));panel.prepend(back);}
  // Keep the five main destinations identical in both workspaces.
  const home=document.querySelector('.seller-nav-tab[data-target-view="dashboard"]');
  if(home){const label=home.querySelector('.seller-nav-label');if(label)label.textContent='Home';else home.lastChild.textContent='Home';}
  const area=seller?document.querySelector('.owner-page-header .eyebrow'):null;if(area)area.textContent='Drop Rate';
  const brand=document.querySelector(seller?'.owner-topbar-brand':'.topbar .brand-lockup');
  if(brand){const logo=document.createElement('img');logo.src=seller?'/assets/brand-assets/seller-hub-approved.webp':'/assets/brand-assets/drop-rate-founder-hq.png';logo.alt=seller?'Drop Rate Seller Hub':'Drop Rate Founder HQ';logo.className='workspace-approved-logo';brand.replaceChildren(logo);}
  const oldSearch=document.querySelector('.workspace-search');if(oldSearch){oldSearch.classList.add('workspace-inventory-search');oldSearch.querySelector('input').placeholder='Search your inventory…';}
})();
