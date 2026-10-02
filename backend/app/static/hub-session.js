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
      // Do not guess between old sessions belonging to different accounts.
      // Existing legacy-only sessions sign in once to establish the shared session.
      removeLegacy();
      try {
        return JSON.parse(sessionStorage.getItem(key));
      } catch (_) {
        sessionStorage.removeItem(key);
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
