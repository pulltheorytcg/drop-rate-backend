/* The collector layer uses the existing role-scoped navigation and catalogue. */
"use strict";
(() => {
  const seller = Boolean(document.getElementById('owner-view-overview'));
  const home = document.getElementById(seller ? 'owner-view-overview' : 'seller-view-dashboard');
  if (!home) return;
  document.body.classList.add('collector-workspace');
  const navigate = view => seller ? activateOwnerView(view === 'home' ? 'overview' : view)
    : activateSellerView(view === 'scan' ? 'intake' : view === 'home' ? 'dashboard' : view, true);
  const worlds = [
    ['ocean', 'One Piece', 'ONE_PIECE_CARD_GAME', 'one-piece-white.png', 'Set sail for your next grail'],
    ['electric', 'Pokémon', 'POKEMON_TCG', 'pokemon.webp', 'Gotta find your favourites'],
    ['ninja', 'Naruto', 'NARUTO_KAYOU', 'naruto.svg', 'Build your shinobi collection'],
    ['energy', 'Dragon Ball', 'DRAGON_BALL_SUPER_MASTERS', 'masters.png', 'Power up your collection'],
  ];
  const el = (tag, cls, text) => { const n=document.createElement(tag); n.className=cls; if(text)n.textContent=text; return n; };
  const action = (label, callback, cls='collector-button') => { const b=el('button',cls,label);b.type='button';b.addEventListener('click',callback);return b; };

  const hero = home.querySelector(seller ? '.owner-hero' : '.founder-hero');
  const copy = hero.querySelector(seller ? '.owner-hero-copy' : '.founder-hero-copy');
  hero.classList.add('collector-hero');
  const greeting=el('p','collector-greeting','WELCOME TO YOUR COLLECTOR HQ');
  const title=el('h1','collector-headline');title.append('Big pulls.',el('br',''),el('em','','Bigger adventures.'));
  const intro=el('p','collector-intro','Your cards. Your worlds. One place to scan, collect and turn your next pull into something more.');
  const buttons=el('div','collector-hero-actions');
  buttons.append(action('Scan a card  ↗',()=>navigate('scan'),'collector-button collector-primary'),action('Explore the catalogue  →',()=>window.openDropRateCatalogue(),'collector-button collector-secondary'));
  const name=hero.querySelector('#owner-overview-name');
  if(name){const hello=el('span','collector-hello','Hey, ');hello.append(name,document.createTextNode(' ✦'));greeting.replaceChildren(hello);}
  copy.replaceChildren(greeting,title,intro,buttons);
  if(!seller)hero.querySelector('.founder-hero-art')?.remove();
  hero.append(el('span','collector-hero-badge','THE NEXT GREAT FIND IS YOURS'));
  hero.querySelectorAll('[data-hero-view]').forEach(b=>b.remove());

  const explore=el('section','collector-explore');explore.setAttribute('aria-labelledby','collector-worlds-title');
  const heading=el('div','collector-section-heading');const headingCopy=el('div','');
  headingCopy.append(el('span','collector-kicker','CHOOSE YOUR NEXT ADVENTURE'));
  const h=el('h2','','Explore your worlds');h.id='collector-worlds-title';headingCopy.append(h);
  heading.append(headingCopy,action('All games  →',()=>window.openDropRateCatalogue(),'collector-text-button'));
  const grid=el('div','collector-world-grid');
  for(const [world,label,system,file,tagline] of worlds){
    const tile=action('',()=>window.openDropRateCatalogue(system),'collector-world');
    tile.dataset.world=world;tile.setAttribute('aria-label','Explore '+label);
    const art=el('div','collector-world-art'),img=el('img','');img.src='/assets/title-art/'+file;img.alt=label;img.decoding='async';
    img.addEventListener('error',()=>{img.remove();art.append(el('strong','',label));});art.append(img);
    const caption=el('div','collector-world-caption');caption.append(el('span','',tagline),el('span','collector-world-arrow','↗'));tile.append(art,caption);grid.append(tile);
  }
  explore.append(heading,grid);hero.after(explore);

  const vibe=el('div','collector-vibes');vibe.setAttribute('aria-label','Workspace colour theme');vibe.append(el('span','','Your vibe'));
  const choices=[['all','All worlds'],...worlds.map(([key,label])=>[key,label])];
  const setVibe=(key,persist=false)=>{document.body.dataset.collectorVibe=key;vibe.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.vibe===key)));if(persist){try{localStorage.setItem('drop-rate-collector-vibe',key);}catch(_){}}};
  for(const [key,label] of choices){const b=action(label,()=>setVibe(key,true),'collector-vibe');b.dataset.vibe=key;vibe.append(b);}
  home.prepend(vibe);let saved='all';try{saved=localStorage.getItem('drop-rate-collector-vibe')||'all';}catch(_){}setVibe(choices.some(([k])=>k===saved)?saved:'all');

  if(seller){
    const kpis=home.querySelector('.owner-kpi-grid');explore.after(kpis);
    const heading=el('div','collector-section-heading collector-stats-heading');heading.append(el('h2','','Your collection, at a glance'),action('Open inventory  →',()=>navigate('inventory'),'collector-text-button'));kpis.before(heading);
    const money=hero.querySelector('.owner-hero-money'),payout=home.querySelector('.owner-payout-tracker');
    const finances=el('section','collector-finance-row');finances.setAttribute('aria-label','Your balance and next payout');finances.append(money,payout);kpis.after(finances);
    const latest=home.querySelector('.owner-latest-panel');finances.after(latest);
    home.querySelector('.owner-kpi-card:nth-child(2) small').textContent='Latest available market prices';
    document.getElementById('owner-page-subtitle').textContent='Welcome to your collecting adventure.';
  }
  const nav=document.querySelector(seller?'.owner-sidebar':'.seller-nav');
  if(nav){const foot=el('div','collector-nav-note');foot.append(el('span','collector-kicker','BUILT FOR COLLECTORS'),el('strong','','Chase the cards.\nEnjoy the journey.'),el('span','collector-nav-star','✦'));nav.append(foot);}
  // Home keeps its own hierarchy; the other tools retain their page heading.
  const updateHome=view=>document.body.classList.toggle('collector-at-home',view===(seller?'overview':'dashboard'));
  document.addEventListener(seller?'owner-view-changed':'seller-view-changed',e=>updateHome(e.detail.view));
  updateHome(home.classList.contains('hidden')?'':'overview'===home.dataset.ownerViewPanel?'overview':'dashboard');
})();
