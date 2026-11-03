/* Shared presentation only. Each hub keeps its existing permission-scoped handlers. */
"use strict";
(() => {
  const seller = Boolean(document.getElementById('owner-view-more'));
  const navigate = view => seller ? activateOwnerView(view) : activateSellerView(view, true);
  const paths = {
    home: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
    collection: 'M7 3h12a2 2 0 0 1 2 2v12 M5 7h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z M7 11h6 M7 15h6',
    scan: 'M8 3H5a2 2 0 0 0-2 2v3 M16 3h3a2 2 0 0 1 2 2v3 M3 16v3a2 2 0 0 0 2 2h3 M21 16v3a2 2 0 0 1-2 2h-3 M7 12h10',
    search: 'M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13z M16 16l5 5',
    more: 'M5 12h.01 M12 12h.01 M19 12h.01',
    selling: 'M3 3h7l11 11-7 7L3 10V3z M7 7h.01',
    verification: 'M9 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-4 M8 12l4 4 9-12',
    media: 'M4 5h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z M3 16l5-5 5 5 3-3 5 5 M16 9h.01',
    sales: 'M5 3h14v18l-3-2-4 2-4-2-3 2V3z M9 7h6 M9 11h6 M9 15h3',
    balance: 'M20 7V5a2 2 0 0 0-2-2H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H5a2 2 0 0 1-2-2V5 M21 11h-5v5h5 M17 13.5h.01',
    settlements: 'M4 7h16 M16 3l4 4-4 4 M20 17H4 M8 13l-4 4 4 4',
    reports: 'M4 3v18h17 M8 16v-5 M13 16V7 M18 16V4',
    channels: 'M8 8l8 8 M8 16l8-8 M3 3h5v5H3z M16 3h5v5h-5z M3 16h5v5H3z M16 16h5v5h-5z',
    settings: 'M4 6h16 M4 12h16 M4 18h16 M8 3v6 M16 9v6 M10 15v6',
    accounts: 'M12 3l9 5v13H3V8l9-5z M8 21v-8h8v8 M8 8h.01 M16 8h.01',
    profile: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z M4 21v-2a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v2',
    arrow: 'M9 5l7 7-7 7',
    back: 'M19 12H5 M11 6l-6 6 6 6',
  };
  const icon = key => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [name, value] of Object.entries({
      viewBox: '0 0 24 24', width: '20', height: '20', fill: 'none',
      stroke: 'currentColor', 'stroke-width': key === 'more' ? '3.5' : '1.7',
      'stroke-linecap': 'round', 'stroke-linejoin': 'round',
      'aria-hidden': 'true', focusable: 'false', class: 'workspace-icon',
    })) svg.setAttribute(name, value);
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', paths[key] || paths.collection);
    svg.append(path);
    return svg;
  };
  const tools = {
    selling: ['Selling', 'Choose items to list and manage their progress'],
    verification: ['Review cards', 'Confirm identities and prepare your stock'],
    media: ['Photos & condition', 'Check artwork, photos and physical condition'],
    sales: ['Sales', 'Orders, fees and owner proceeds'],
    balance: ['Payouts', 'Balances, payout history and schedules'],
    settlements: ['Settlements', 'Order allocations and reconciliation'],
    reports: ['Reports', 'Track performance and inventory value'],
    channels: ['Sales channels', 'Shopify, eBay and channel status'],
    settings: [seller ? 'Settings' : 'Settings & channels', seller ? 'Appearance and workspace settings' : 'Appearance, store connections and workspace settings'],
    accounts: ['Business', 'Company overview, sellers and stock ownership'],
    profile: ['Your account', 'Profile, contact details and sign-in settings'],
  };
  const groups = [
    ['Collection tools', ['verification', 'media']],
    ['Selling', ['selling', 'sales', 'channels']],
    ['Payouts & finance', ['balance', 'settlements', 'reports']],
    ['Account & settings', ['profile', 'settings', 'accounts']],
  ];
  const more = document.getElementById(seller ? 'owner-view-more' : 'seller-view-more');
  const old = more?.querySelector('.app-more-grid');
  // These are the role's existing controls, not a new list of entitlements.
  const buttons = new Map([...(old?.querySelectorAll('button') || [])]
    .map(button => [seller ? button.dataset.ownerJump : button.dataset.moreView, button]));
  if (old) {
    for (const [title, keys] of groups) {
      const existing = keys.filter(key => buttons.has(key));
      if (!existing.length) continue;
      const section = document.createElement('section');
      section.className = 'workspace-tool-group';
      const heading = document.createElement('h2');
      heading.textContent = title;
      section.append(heading);
      const grid = document.createElement('div');
      grid.className = 'workspace-tool-grid';
      for (const key of existing) {
        const button = buttons.get(key);
        const [label, description] = tools[key];
        const symbol = document.createElement('span');
        symbol.className = 'workspace-tool-icon';
        symbol.setAttribute('aria-hidden', 'true');
        symbol.append(icon(key));
        const copy = document.createElement('span');
        const strong = document.createElement('strong');
        const small = document.createElement('small');
        strong.textContent = label;
        small.textContent = description;
        copy.append(strong, small);
        button.replaceChildren(symbol, copy, icon('arrow'));
        grid.append(button);
      }
      section.append(grid);
      more.append(section);
    }
    old.remove();
  }
  const panels = seller ? [...document.querySelectorAll('[data-owner-view-panel]')]
    : [...document.querySelectorAll('[data-seller-view]')];
  for (const panel of panels) {
    const key = seller ? panel.dataset.ownerViewPanel : panel.dataset.sellerView;
    if (!tools[key]) continue;
    const back = document.createElement('button');
    back.type = 'button';
    back.className = 'workspace-back';
    back.append(icon('back'), document.createTextNode('More tools'));
    back.addEventListener('click', () => {
      navigate('more');
      buttons.get(key)?.focus();
    });
    panel.prepend(back);
  }

  // Preserve the five primary destinations and their existing click/keyboard handlers.
  const primaryKeys = {overview: 'home', dashboard: 'home', inventory: 'collection', intake: 'scan', scan: 'scan', search: 'search', more: 'more'};
  const primaryButtons = [...document.querySelectorAll(seller ? '.owner-nav .owner-nav-item' : '.seller-nav .seller-nav-tab')];
  for (const button of primaryButtons) {
    const key = seller ? button.dataset.ownerView : button.dataset.targetView;
    const previousIcon = button.querySelector(seller ? 'svg, span[aria-hidden="true"]' : '.seller-nav-icon');
    const symbol = icon(primaryKeys[key]);
    if (previousIcon) previousIcon.replaceWith(symbol);
    else button.prepend(symbol);
    if (key === 'dashboard') {
      const label = button.querySelector('.seller-nav-label') || button.querySelector('span:last-child');
      if (label) label.textContent = 'Home';
    }
  }
  const nav = document.querySelector(seller ? '.owner-sidebar' : '.seller-nav');
  if (nav) {
    if (!seller) {
      // Keep navigation shortcuts outside the five-tab ARIA set.
      const primary = document.createElement('div');
      primary.className = 'workspace-primary-nav';
      primary.setAttribute('role', 'tablist');
      primary.setAttribute('aria-label', 'Main workspace');
      primary.append(...primaryButtons);
      nav.prepend(primary);
      nav.removeAttribute('role');
      const orientation = () => {
        primary.setAttribute('aria-orientation', window.innerWidth > 1000 ? 'vertical' : 'horizontal');
        nav.removeAttribute('aria-orientation');
      };
      orientation();
      window.addEventListener('resize', orientation);
    }
    const secondary = document.createElement('nav');
    secondary.className = 'workspace-secondary-nav';
    secondary.setAttribute('aria-label', 'Selling and payouts');
    const heading = document.createElement('p');
    heading.className = 'workspace-nav-heading';
    heading.textContent = 'Selling & payouts';
    secondary.append(heading);
    for (const key of ['selling', 'sales', 'balance']) {
      const source = buttons.get(key);
      if (!source || source.hidden || source.disabled || source.getAttribute('aria-hidden') === 'true') continue;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'workspace-secondary-link';
      button.dataset.workspaceView = key;
      button.setAttribute('aria-controls', seller ? `owner-view-${key}` : `seller-view-${key}`);
      const label = document.createElement('span');
      label.textContent = tools[key][0];
      button.append(icon(key), label);
      button.addEventListener('click', () => navigate(key));
      secondary.append(button);
    }
    if (secondary.querySelector('button')) nav.append(secondary);
    const updateSecondary = view => secondary.querySelectorAll('[data-workspace-view]').forEach(button => {
      const active = button.dataset.workspaceView === view;
      button.classList.toggle('active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
    document.addEventListener(seller ? 'owner-view-changed' : 'seller-view-changed', event => updateSecondary(event.detail.view));
    const active = panels.find(panel => !panel.classList.contains('hidden'));
    updateSecondary(seller ? active?.dataset.ownerViewPanel : active?.dataset.sellerView);
  }

  const area = seller ? document.querySelector('.owner-page-header .eyebrow') : null;
  if (area) area.textContent = 'Drop Rate';
  const brand = document.querySelector(seller ? '.owner-topbar-brand' : '.topbar .brand-lockup');
  if (brand) {
    const logo = document.createElement('img');
    logo.src = '/assets/brand-assets/storefront-logo.png';
    logo.alt = 'Drop Rate';
    logo.className = 'workspace-approved-logo';
    const label = document.createElement('span');
    label.className = 'workspace-brand-caption';
    label.textContent = seller ? 'Seller Hub' : 'Founder HQ';
    brand.replaceChildren(logo, label);
  }
  const oldSearch = document.querySelector('.workspace-search');
  if (oldSearch) {
    oldSearch.classList.add('workspace-inventory-search');
    oldSearch.querySelector('input').placeholder = 'Search your inventory…';
  }
})();
