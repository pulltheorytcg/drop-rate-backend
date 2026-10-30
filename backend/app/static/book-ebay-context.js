"use strict";

// Active listings are edition-level shopping context. They never set a market
// value, physical-copy identity, condition, inventory total or approved image.
window.DropRateBookEbay = (() => {
  const element = (tag, cls = "", text = "") => { const node = document.createElement(tag); node.className = cls; node.textContent = text; return node; };
  const money = value => new Intl.NumberFormat("en-GB", {style:"currency", currency:"GBP"}).format(value / 100);
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const amount = value => Number.isSafeInteger(value) && value > 0;
  const short = (value, length) => typeof value === "string" && value.trim() && value.length <= length;
  function isbn(value) {
    let code = String(value || "").replace(/[-\s]/g, "").toUpperCase();
    if (/^[0-9]{9}[0-9X]$/.test(code)) {
      if ([...code].reduce((sum, digit, i) => sum + (digit === "X" ? 10 : Number(digit)) * (10 - i), 0) % 11) return null;
      code = "978" + code.slice(0, 9);
      code += String((10 - [...code].reduce((sum, digit, i) => sum + Number(digit) * (i % 2 ? 3 : 1), 0) % 10) % 10);
    }
    return /^97[89][0-9]{10}$/.test(code) && [...code].reduce((sum, digit, i) => sum + Number(digit) * (i % 2 ? 3 : 1), 0) % 10 === 0 ? code : null;
  }
  function identity(row) {
    const book = row?.book_details;
    if (row?.product_type !== "COMIC" || !uuid.test(row.catalogue_id || "") || !book) return null;
    const code = isbn(book.barcode_gtin), language = row.language || book.language;
    if (!code || !short(book.series_title, 140) || !short(book.issue_number, 40) || !short(language, 80)) return null;
    const declared = String(book.volume_identifier || "").trim().toLowerCase().replace(/\s+/g," ");
    const binding = book.book_format === "HARDCOVER" ? "Hardcover" : book.book_format === "TRADE_PAPERBACK" ? "Paperback"
      : ["paperback","paper back","trade paperback","softcover","soft cover"].includes(declared) ? "Paperback"
      : ["hardcover","hard cover","hardback","hard back"].includes(declared) ? "Hardcover" : null;
    const target = {catalogue_id:row.catalogue_id, isbn:code, title:book.series_title, volume:book.issue_number, language, binding};
    target.key = JSON.stringify([target, book.system_code, book.book_format, book.volume_identifier, book.publisher,
      book.release_year, book.printing_number, book.cover_code, book.cover_artist]);
    return target;
  }
  function externalUrl(value, photo = false) {
    if (typeof value !== "string" || value.length > 2000) return null;
    try {
      const url = new URL(value);
      if (url.protocol !== "https:" || url.username || url.password || url.port || url.hash) return null;
      if (photo) {
        if (url.hostname !== "i.ebayimg.com" || !/^\/images\/g\/[A-Za-z0-9_~=-]+\/s-l[0-9]{2,4}\.(?:jpe?g|png|webp)$/i.test(url.pathname) || url.search) return null;
      } else if (!["www.ebay.co.uk", "ebay.co.uk", "www.ebay.com", "ebay.com"].includes(url.hostname)
        || !/^\/itm\/(?:[^/]+\/)?[0-9]+\/?$/.test(url.pathname)) return null;
      return url.href;
    } catch (_) { return null; }
  }
  function validate(row, data, now = Date.now()) {
    const target = identity(row);
    if (!target || !data || data.catalogue_id !== target.catalogue_id || data.source !== "EBAY_BROWSE"
      || data.observation_type !== "ACTIVE" || data.scope !== "EDITION_ACTIVE_LISTINGS"
      || data.currency !== "GBP" || data.physical_valuation_eligible !== false
      || !["AVAILABLE", "UNAVAILABLE", "DISABLED"].includes(data.status)) return null;
    const checked = Date.parse(data.checked_at), expiry = Date.parse(data.expires_at);
    if (!Number.isFinite(checked) || !Number.isFinite(expiry) || checked > now + 60000 || expiry <= now
      || expiry <= checked || expiry - checked > 3601000) return null;
    if (data.status !== "AVAILABLE") {
      return data.item_count === 0 && Array.isArray(data.items) && !data.items.length
        && data.asking_low_minor == null && data.asking_high_minor == null ? {...data, items:[]} : null;
    }
    if (data.isbn !== target.isbn || !/^[a-f0-9]{64}$/.test(data.edition_digest || "")
      || !data.edition || data.edition.title !== target.title || data.edition.volume !== target.volume
      || data.edition.language !== target.language || data.edition.binding !== target.binding
      || !Array.isArray(data.items) || data.items.length < 1 || data.items.length > 3 || data.item_count !== data.items.length) return null;
    const items = [], ids = new Set();
    for (const item of data.items) {
      const url = externalUrl(item.url);
      if (!short(item.item_id, 150) || ids.has(item.item_id) || !short(item.title, 500) || !short(item.condition, 200)
        || !["Paperback", "Hardcover"].includes(item.binding) || (target.binding && item.binding !== target.binding)
        || !amount(item.price_minor) || !(item.shipping_minor == null || (Number.isSafeInteger(item.shipping_minor) && item.shipping_minor >= 0))
        || !url || !Number.isFinite(Date.parse(item.checked_at))) return null;
      ids.add(item.item_id);
      items.push({...item, url, image_url:externalUrl(item.image_url, true)});
    }
    if (data.asking_low_minor !== Math.min(...items.map(item => item.price_minor))
      || data.asking_high_minor !== Math.max(...items.map(item => item.price_minor))) return null;
    return {...data, items};
  }
  function context(row) { return validate(row, row?.book_listing_context); }
  function photos(row, data = context(row)) {
    const checked = validate(row, data);
    return checked?.status === "AVAILABLE" ? checked.items.filter(item => item.image_url) : [];
  }
  function link(text, url) {
    const anchor = element("a", "", text); anchor.href = url; anchor.target = "_blank"; anchor.rel = "noopener noreferrer";
    anchor.addEventListener("click", event => event.stopPropagation()); return anchor;
  }
  function photoCredit(item) {
    const note = element("p", "book-ebay-photo-credit");
    note.append(link("eBay listing photo", item.url), document.createTextNode(" · Copy may vary")); return note;
  }
  function render(target, row, data, {detail = false, loading = false, expired = false, refresh = null} = {}) {
    target.replaceChildren(); target.className = detail ? "book-ebay-context book-ebay-detail" : "book-ebay-context book-ebay-grid";
    const checked = validate(row, data);
    target.hidden = checked?.status === "DISABLED";
    if (target.hidden) return;
    if (checked?.status !== "AVAILABLE") {
      target.append(element("p", "book-ebay-empty", loading ? "Checking eBay asking prices…" : expired ? "eBay asking prices have expired."
        : detail ? "No matching eBay asking prices available right now." : "eBay asking prices unavailable"));
      if (expired && refresh) {
        const retry = element("button", "book-ebay-refresh", "Refresh asking prices");
        retry.type = "button";
        retry.addEventListener("click", event => { event.stopPropagation(); retry.disabled = true; refresh(); });
        target.append(retry);
      }
      return;
    }
    target.append(element(detail ? "h4" : "strong", "book-ebay-heading", checked.item_count === 1 ? "eBay asking price" : "eBay asking prices"));
    target.append(element("span", "book-ebay-range", money(checked.asking_low_minor)
      + (checked.asking_high_minor === checked.asking_low_minor ? "" : "–" + money(checked.asking_high_minor))));
    if (detail) {
      target.append(element("p", "book-ebay-note", "Active listings for this ISBN edition. Asking prices exclude postage and do not establish your copy’s market value or printing."));
      const list = element("ul", "book-ebay-listings");
      for (const item of checked.items) {
        const entry = element("li"); entry.append(link(item.title + " ↗", item.url));
        const postage = item.shipping_minor == null ? "Postage not stated" : item.shipping_minor === 0 ? "Free postage" : money(item.shipping_minor) + " postage";
        entry.append(element("span", "book-ebay-item-price", money(item.price_minor) + " · " + postage),
          element("small", "", item.condition + " · " + item.binding)); list.append(entry);
      }
      target.append(list, element("small", "book-ebay-checked", "Checked " + new Date(checked.checked_at).toLocaleString("en-GB", {day:"numeric", month:"short", hour:"2-digit", minute:"2-digit"})));
    } else {
      target.append(element("small", "book-ebay-note", [...new Set(checked.items.map(item => item.condition))].join(" / ") + " · plus postage where applicable"));
      const sources = element("span", "book-ebay-sources");
      checked.items.forEach((item, index) => { const source = link("Listing " + (index + 1) + " ↗", item.url); source.title = item.title; sources.append(source); });
      target.append(sources);
    }
  }

  class Session {
    constructor({client, active, root}) {
      this.client = client; this.owner = client.owner; this.active = active; this.root = root; this.epoch = 0;
      this.watchers = new Set(); this.jobs = new Map(); this.queue = []; this.running = new Set(); this.cache = new Map();
      if (typeof window.IntersectionObserver === "function") this.observer = new window.IntersectionObserver(entries => {
        for (const entry of entries) if (entry.isIntersecting) for (const watcher of this.watchers) if (watcher.element === entry.target) this.start(watcher);
      }, {root, rootMargin:"80px 0px"});
      this.checkVisible = () => {
        const bounds = this.root.getBoundingClientRect();
        for (const watcher of this.watchers) {
          const rect = watcher.element.getBoundingClientRect();
          if (!watcher.started && rect.width > 0 && rect.height > 0 && rect.bottom >= bounds.top && rect.top <= bounds.bottom) this.start(watcher);
        }
      };
      if (!this.observer) { root.addEventListener("scroll", this.checkVisible, {passive:true}); window.addEventListener("resize", this.checkVisible); }
    }
    live() { return !this.destroyed && typeof this.owner === "string" && Boolean(this.owner) && this.client.owner === this.owner && this.client.active() && this.active(); }
    valid(watcher) { return this.live() && watcher.epoch === this.epoch && this.watchers.has(watcher) && watcher.element.isConnected && identity(watcher.row)?.key === watcher.key && watcher.current(); }
    watch(row, element, receive, {immediate = false, current = () => true, allowPriced = false} = {}) {
      const target = identity(row);
      if (!target || (!allowPriced && row.market_value_minor != null)) return () => {};
      for (const watcher of this.watchers) if (!watcher.element.isConnected) this.stop(watcher);
      const watcher = {row, element, receive, key:target.key, epoch:this.epoch, current, started:false, timer:null};
      this.watchers.add(watcher);
      if (immediate) queueMicrotask(() => this.start(watcher));
      else if (this.observer) this.observer.observe(element);
      else queueMicrotask(this.checkVisible);
      return () => this.stop(watcher);
    }
    stop(watcher) {
      this.watchers.delete(watcher); clearTimeout(watcher.timer); this.observer?.unobserve(watcher.element);
      const job = this.jobs.get(watcher.key);
      if (job && !job.watchers.some(item => this.valid(item))) { job.controller?.abort(); this.jobs.delete(job.key); this.queue = this.queue.filter(item => item !== job); }
    }
    deliver(watcher, data, options = {}) {
      if (!this.valid(watcher)) return;
      clearTimeout(watcher.timer);
      if (data?.status === "AVAILABLE") watcher.row.book_listing_context = data;
      else delete watcher.row.book_listing_context;
      watcher.receive(data, options);
      if (data) watcher.timer = setTimeout(() => {
        this.cache.delete(watcher.key);
        this.deliver(watcher, null, {expired:true, refresh:() => {
          if (!this.valid(watcher)) return;
          watcher.started = false;
          this.start(watcher);
        }});
      }, Math.max(1, Date.parse(data.expires_at) - Date.now()));
    }
    start(watcher) {
      if (watcher.started || !this.valid(watcher)) return;
      watcher.started = true; this.observer?.unobserve(watcher.element);
      const cached = this.cache.get(watcher.key), data = cached && validate(watcher.row, cached.data);
      if (data && data.edition_digest === cached.digest) { this.deliver(watcher, data); return; }
      this.cache.delete(watcher.key);
      const pending = this.jobs.get(watcher.key);
      if (pending) { pending.watchers.push(watcher); this.deliver(watcher, null, {loading:true}); return; }
      const job = {key:watcher.key, row:watcher.row, epoch:this.epoch, watchers:[watcher]};
      this.jobs.set(job.key, job); this.queue.push(job); this.deliver(watcher, null, {loading:true}); this.drain();
    }
    drain() {
      if (!this.live()) return;
      while (this.running.size < 2 && this.queue.length) {
        const job = this.queue.shift();
        if (this.jobs.get(job.key) !== job || !job.watchers.some(watcher => this.valid(watcher))) continue;
        job.controller = new AbortController(); this.running.add(job);
        const timeout = setTimeout(() => job.controller.abort(), 50000);
        (async () => {
          try {
            const target = identity(job.row);
            if (!target || target.key !== job.key) return;
            const response = await this.client.request(`/api/v1/catalogue-browser/books/${target.catalogue_id}/listing-context`, {signal:job.controller.signal});
            if (job.controller.signal.aborted || job.epoch !== this.epoch || !job.watchers.some(watcher => this.valid(watcher))) return;
            const data = validate(job.row, response);
            if (data) {
              this.cache.delete(job.key); this.cache.set(job.key, {data, digest:data.edition_digest});
              while (this.cache.size > 80) this.cache.delete(this.cache.keys().next().value);
            }
            for (const watcher of job.watchers) this.deliver(watcher, data);
          } catch (_) {
            for (const watcher of job.watchers) this.deliver(watcher, null);
          } finally {
            clearTimeout(timeout); this.running.delete(job); if (this.jobs.get(job.key) === job) this.jobs.delete(job.key); this.drain();
          }
        })();
      }
    }
    reset(clearCache = false) {
      this.epoch++; this.observer?.disconnect();
      for (const watcher of this.watchers) clearTimeout(watcher.timer);
      this.watchers.clear(); this.queue = []; this.jobs.clear();
      for (const job of this.running) job.controller.abort();
      if (clearCache) this.cache.clear();
    }
    destroy() { this.destroyed = true; this.reset(true); this.root.removeEventListener("scroll", this.checkVisible); window.removeEventListener("resize", this.checkVisible); }
  }
  return Object.freeze({Session, identity, validate, context, photos, photoCredit, render});
})();
