/* One tab-scoped session for the two existing hubs. Authorization stays in /access/me. */
(function () {
  "use strict";
  const key = "drop_rate_hub_session";
  let refreshPromise = null;
  const legacyKeys = ["drop_rate_owner_session", "drop_rate_founder_session"];
  function removeLegacy() {
    legacyKeys.forEach(legacy => sessionStorage.removeItem(legacy));
  }
  window.PullTheoryHubSession = Object.freeze({
    showFailure(message) {
      const panel=document.querySelector('.hub-loading');if(!panel)return;
      panel.querySelector('strong').textContent=message;
      if(!panel.querySelector('button')){const retry=document.createElement('button');retry.type='button';retry.textContent='Retry';retry.onclick=()=>window.location.reload();panel.append(retry);}
      document.body.classList.add('hub-restoring');
    },
    refresh(task) {
      if (!refreshPromise) refreshPromise = Promise.resolve().then(task).finally(() => { refreshPromise = null; });
      return refreshPromise;
    },
    read() {
      try {
        let session = JSON.parse(sessionStorage.getItem(key));
        if (!session?.access_token) {
          // Older invitation pages wrote a different key. Carry a single session
          // forward; the server still verifies its role before any hub opens.
          const candidates = legacyKeys.map(legacy => {
            try { return JSON.parse(sessionStorage.getItem(legacy)); } catch (_) { return null; }
          }).filter(value => value?.access_token);
          if (candidates.length && candidates.every(value => value.access_token === candidates[0].access_token)) {
            session = candidates[0];
            sessionStorage.setItem(key, JSON.stringify(session));
          }
        }
        removeLegacy();
        return session;
      } catch (_) {
        sessionStorage.removeItem(key);
        removeLegacy();
        return null;
      }
    },
    save(session) {
      removeLegacy();
      sessionStorage.setItem(key, JSON.stringify(session));
    },
    clear() {
      sessionStorage.removeItem(key);
      removeLegacy();
      window.dispatchEvent(new Event("hub-session-cleared"));
    },
  });
})();
