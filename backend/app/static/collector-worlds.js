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
    ['ocean', 'One Piece', 'ONE_PIECE_CARD_GAME', 'one-piece-white.png', 'Explore One Piece'],
    ['electric', 'Pokémon', 'POKEMON_TCG', 'pokemon.webp', 'Explore Pokémon'],
    ['ninja', 'Naruto', 'NARUTO', 'naruto.svg', 'Explore Naruto'],
    ['energy', 'Dragon Ball', 'DRAGON_BALL_SUPER_MASTERS', 'masters.png', 'Explore Dragon Ball'],
  ];
  const el = (tag, cls, text) => { const n=document.createElement(tag); n.className=cls; if(text)n.textContent=text; return n; };
  const action = (label, callback, cls='collector-button') => { const b=el('button',cls,label);b.type='button';b.addEventListener('click',callback);return b; };
  const browseGame = (system='') => window.openDropRateCatalogue(system, '', {reset:true});

  const hero = home.querySelector(seller ? '.owner-hero' : '.founder-hero');
  const copy = hero.querySelector(seller ? '.owner-hero-copy' : '.founder-hero-copy');
  hero.classList.add('collector-hero');
  const greeting=el('p','collector-greeting',seller?'YOUR SELLER WORKSPACE':'YOUR DAILY OVERVIEW');
  const title=el('h1','collector-headline');
  if(seller)title.textContent='Your collection.';
  else title.append('Your collection.',el('br',''),el('em','','Under control.'));
  const intro=el('p','collector-intro',seller?'Every find, in one place.':'Your stock, reviews and sales, in one place.');
  const buttons=el('div','collector-hero-actions');
  buttons.append(action('Add item',()=>window.DropRateHub?.openAdd?.() || browseGame(),'collector-button collector-primary'),action('Scan',()=>seller?activateOwnerView('scan',true,true):navigate('scan'),'collector-button collector-secondary'));
  const name=hero.querySelector('#owner-overview-name');
  if(name){const hello=el('span','collector-hello','Welcome back, ');hello.append(name);greeting.replaceChildren(hello);}
  copy.replaceChildren(greeting,title,intro,buttons);
  if(!seller)hero.querySelector('.founder-hero-art')?.remove();
  const spotlight=el('section','collector-grails');spotlight.setAttribute('aria-label','The collector’s edit');
  const cards=el('div','collector-grail-grid');
  const grails=[
    ['Umbreon VMAX','215/203 · Evolving Skies','umbreon-vmax-215.webp','r:f44ea051229d320c9c7b413368ab7955'],
    ['Monkey.D.Luffy','OP05-119 · Manga','luffy-op05-119-p2.png','r:f4e35a3f027185c5e85b343828cbc26a'],
    ['Son Goku','FB01-139 · Super alt art','goku-fb01-139-p2.webp','r:604f17c87635175c6422e00915eb568b'],
  ];
  for(const [name,printing,file,key] of grails){
    const card=action('',()=>window.openDropRateCatalogue('',key),'collector-grail');
    card.setAttribute('aria-label','View '+name+' · '+printing);card.dataset.productKey=key;
    const img=el('img','');img.src='/assets/grail-art/'+file;img.alt=name+' · '+printing;img.decoding='async';
    img.addEventListener('error',()=>{img.hidden=true;card.classList.add('art-unavailable');});
    card.append(img,el('strong','',name),el('span','',printing));cards.append(card);
  }
  spotlight.append(el('p','collector-grail-heading','THE COLLECTOR’S EDIT'),cards,el('p','collector-grail-hint','Reference artwork · Select a card to explore'));
  if(!seller)hero.append(spotlight);
  hero.querySelectorAll('[data-hero-view]').forEach(b=>b.remove());

  const explore=el('section','collector-explore');explore.setAttribute('aria-labelledby','collector-worlds-title');
  const heading=el('div','collector-section-heading');const headingCopy=el('div','');
  headingCopy.append(el('span','collector-kicker','THE CATALOGUE'));
  const h=el('h2','','Find your next addition.');h.id='collector-worlds-title';headingCopy.append(h);
  heading.append(headingCopy,action('Browse all',()=>browseGame(),'collector-text-button'));
  const grid=el('div','collector-world-grid');
  for(const [world,label,system,file,tagline] of worlds){
    const tile=action('',()=>browseGame(system),'collector-world');
    tile.dataset.world=world;tile.setAttribute('aria-label','Explore '+label);
    const art=el('div','collector-world-art'),img=el('img','');img.src='/assets/title-art/'+file;img.alt=label;img.decoding='async';
    img.addEventListener('error',()=>{img.remove();art.append(el('strong','',label));});art.append(img);
    const caption=el('div','collector-world-caption');caption.append(el('span','',tagline),el('span','collector-world-arrow','↗'));tile.append(art,caption);grid.append(tile);
  }
  explore.append(heading,grid);if(!seller)hero.after(explore);

  const games=el('nav','collector-games');games.setAttribute('aria-label','Browse games');games.append(el('span','','Browse games'));
  for(const [system,label] of [['','All games'],...worlds.map(([,label,system])=>[system,label])]){
    const b=action(label,()=>browseGame(system),'collector-game');b.dataset.systemCode=system;games.append(b);
  }
  if(!seller)home.prepend(games);

  const appearance=el('section','collector-appearance');appearance.setAttribute('aria-labelledby','collector-appearance-title');
  const appearanceTitle=el('h2','','Appearance');appearanceTitle.id='collector-appearance-title';
  appearance.append(appearanceTitle,el('p','','Choose an accent for your dark workspace. Saved on this device.'));
  const vibe=el('div','collector-vibes');vibe.setAttribute('role','group');vibe.setAttribute('aria-label','Workspace accent');
  // Preserve saved keys while keeping the workspace consistently dark.
  const choices=[['all','Default'],['ocean','Ocean'],['electric','Gold'],['ninja','Ember'],['energy','Violet']];
  const setVibe=(key,persist=false)=>{document.body.dataset.collectorVibe=key;vibe.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.vibe===key)));if(persist){try{localStorage.setItem('drop-rate-collector-vibe',key);}catch(_){}}};
  for(const [key,label] of choices){const b=action(label,()=>setVibe(key,true),'collector-vibe');b.dataset.vibe=key;vibe.append(b);}
  appearance.append(vibe);
  const settings=document.getElementById(seller?'owner-view-settings':'seller-view-settings');
  const settingsHeading=settings.querySelector('.seller-view-heading') || settings.querySelector('.workspace-back');
  if(settingsHeading)settingsHeading.after(appearance);else settings.prepend(appearance);
  let saved='all';try{saved=localStorage.getItem('drop-rate-collector-vibe')||'all';}catch(_){}setVibe(choices.some(([k])=>k===saved)?saved:'all');

  if(seller){
    const kpis=home.querySelector('.owner-kpi-grid');
    const heading=el('div','collector-section-heading collector-stats-heading');heading.append(el('h2','','At a glance'),action('View collection',()=>navigate('inventory'),'collector-text-button'));
    const latest=home.querySelector('.owner-latest-panel');hero.after(heading,kpis,latest);
    document.getElementById('owner-page-subtitle').textContent='Your collection, at a glance.';
  }
  const nav=document.querySelector(seller?'.owner-sidebar':'.seller-nav');
  if(nav){
    const foot=el('div','collector-nav-note');
    const store=el('a','workspace-storefront-link','Visit the storefront');
    store.href='https://droprate.co.uk/';store.target='_blank';store.rel='noopener noreferrer';
    store.setAttribute('aria-label','Visit the Drop Rate storefront (opens in a new tab)');
    foot.append(el('span','collector-kicker','DROP RATE STORE'),store);nav.append(foot);
  }
  // Home keeps its own hierarchy; the other tools retain their page heading.
  const updateHome=view=>document.body.classList.toggle('collector-at-home',view===(seller?'overview':'dashboard'));
  document.addEventListener(seller?'owner-view-changed':'seller-view-changed',e=>updateHome(e.detail.view));
  updateHome(home.classList.contains('hidden')?'':'overview'===home.dataset.ownerViewPanel?'overview':'dashboard');
})();
