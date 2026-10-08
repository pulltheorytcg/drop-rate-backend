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
    ['ninja', 'Naruto', 'NARUTO', 'naruto.svg', 'Build your shinobi collection'],
    ['energy', 'Dragon Ball', 'DRAGON_BALL_SUPER_MASTERS', 'masters.png', 'Power up your collection'],
  ];
  const el = (tag, cls, text) => { const n=document.createElement(tag); n.className=cls; if(text)n.textContent=text; return n; };
  const action = (label, callback, cls='collector-button') => { const b=el('button',cls,label);b.type='button';b.addEventListener('click',callback);return b; };
  const browseGame = (system='') => window.openDropRateCatalogue(system, '', {reset:true});

  const hero = home.querySelector(seller ? '.owner-hero' : '.founder-hero');
  const copy = hero.querySelector(seller ? '.owner-hero-copy' : '.founder-hero-copy');
  hero.classList.add('collector-hero');
  const greeting=el('p','collector-greeting','WELCOME TO YOUR COLLECTOR HQ');
  const title=el('h1','collector-headline');title.append('Find your',el('br',''),el('em','','next grail.'));
  const intro=el('p','collector-intro','From your first pull to your dream collection. Discover the cards you love.');
  const buttons=el('div','collector-hero-actions');
  buttons.append(action('Scan a card  ↗',()=>navigate('scan'),'collector-button collector-primary'),action('Explore cards  →',()=>browseGame(),'collector-button collector-secondary'));
  const name=hero.querySelector('#owner-overview-name');
  if(name){const hello=el('span','collector-hello','Hey, ');hello.append(name,document.createTextNode(' ✦'));greeting.replaceChildren(hello);}
  copy.replaceChildren(greeting,title,intro,buttons);
  if(!seller)hero.querySelector('.founder-hero-art')?.remove();
  const spotlight=el('section','collector-grails');spotlight.setAttribute('aria-label','Grail spotlight');
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
  spotlight.append(el('p','collector-grail-heading','GRAIL SPOTLIGHT'),cards,el('p','collector-grail-hint','Reference artwork · Tap a card to explore ↗'));
  hero.append(spotlight);
  hero.querySelectorAll('[data-hero-view]').forEach(b=>b.remove());

  const explore=el('section','collector-explore');explore.setAttribute('aria-labelledby','collector-worlds-title');
  const heading=el('div','collector-section-heading');const headingCopy=el('div','');
  headingCopy.append(el('span','collector-kicker','CHOOSE YOUR NEXT ADVENTURE'));
  const h=el('h2','','Explore your worlds');h.id='collector-worlds-title';headingCopy.append(h);
  heading.append(headingCopy,action('All games  →',()=>browseGame(),'collector-text-button'));
  const grid=el('div','collector-world-grid');
  for(const [world,label,system,file,tagline] of worlds){
    const tile=action('',()=>browseGame(system),'collector-world');
    tile.dataset.world=world;tile.setAttribute('aria-label','Explore '+label);
    const art=el('div','collector-world-art'),img=el('img','');img.src='/assets/title-art/'+file;img.alt=label;img.decoding='async';
    img.addEventListener('error',()=>{img.remove();art.append(el('strong','',label));});art.append(img);
    const caption=el('div','collector-world-caption');caption.append(el('span','',tagline),el('span','collector-world-arrow','↗'));tile.append(art,caption);grid.append(tile);
  }
  explore.append(heading,grid);hero.after(explore);

  const games=el('nav','collector-games');games.setAttribute('aria-label','Browse games');games.append(el('span','','Browse games'));
  for(const [system,label] of [['','All games'],...worlds.map(([,label,system])=>[system,label])]){
    const b=action(label,()=>browseGame(system),'collector-game');b.dataset.systemCode=system;games.append(b);
  }
  home.prepend(games);

  const appearance=el('section','collector-appearance');appearance.setAttribute('aria-labelledby','collector-appearance-title');
  const appearanceTitle=el('h2','','Appearance');appearanceTitle.id='collector-appearance-title';
  appearance.append(appearanceTitle,el('p','','Choose your workspace colour theme. Saved on this device.'));
  const vibe=el('div','collector-vibes');vibe.setAttribute('role','group');vibe.setAttribute('aria-label','Workspace colour theme');
  const choices=[['all','All worlds'],...worlds.map(([key,label])=>[key,label])];
  const setVibe=(key,persist=false)=>{document.body.dataset.collectorVibe=key;vibe.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.vibe===key)));if(persist){try{localStorage.setItem('drop-rate-collector-vibe',key);}catch(_){}}};
  for(const [key,label] of choices){const b=action(label,()=>setVibe(key,true),'collector-vibe');b.dataset.vibe=key;vibe.append(b);}
  appearance.append(vibe);
  const settings=document.getElementById(seller?'owner-view-settings':'seller-view-settings');
  const settingsHeading=settings.querySelector('.seller-view-heading') || settings.querySelector('.workspace-back');
  if(settingsHeading)settingsHeading.after(appearance);else settings.prepend(appearance);
  let saved='all';try{saved=localStorage.getItem('drop-rate-collector-vibe')||'all';}catch(_){}setVibe(choices.some(([k])=>k===saved)?saved:'all');

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
