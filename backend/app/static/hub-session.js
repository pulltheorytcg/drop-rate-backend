/* One tab-scoped session for the two existing hubs. Authorization stays in /access/me. */
(function () {
  "use strict";
  const key = "drop_rate_hub_session";
  let refreshPromise = null;
  let sessionEpoch = 0;
  const legacyKeys = ["drop_rate_owner_session", "drop_rate_founder_session"];
  const expiredRefreshCodes = new Set([
    "refresh_token_not_found", "refresh_token_already_used", "session_not_found", "session_expired",
  ]);
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
    capture(getSession) {
      // A token refresh is the same account; logout/replacement is a new context.
      // Recheck after body decoding too: fetch resolving is not the end of a read.
      const original = getSession(), epoch = sessionEpoch;
      const owner = original?.user?.id;
      return () => {
        const current = getSession();
        if (sessionEpoch !== epoch || !current?.access_token ||
            (owner ? current.user?.id !== owner : current !== original)) {
          const error = new Error("Your account changed. Please retry from your current account.");
          error.name = "AbortError";
          error.code = "SESSION_CHANGED";
          error.refreshSession = original;
          throw error;
        }
      };
    },
    refresh(task) {
      if (!refreshPromise) {
        const pending = Promise.resolve().then(task).finally(() => {
          // An old account's completion cannot clear a newer refresh in flight.
          if (refreshPromise === pending) refreshPromise = null;
        });
        refreshPromise = pending;
      }
      return refreshPromise;
    },
    isExpiredRefresh(error) {
      return [401, 403].includes(error.status)
        || (error.status === 400 && expiredRefreshCodes.has(error.code));
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
      let previous;
      try { previous = JSON.parse(sessionStorage.getItem(key)); } catch (_) { previous = null; }
      if (previous?.user?.id && session?.user?.id && previous.user.id !== session.user.id) {
        sessionEpoch++;
        refreshPromise = null;
        window.dispatchEvent(new Event("hub-session-cleared"));
      }
      removeLegacy();
      sessionStorage.setItem(key, JSON.stringify(session));
    },
    clear() {
      sessionEpoch++;
      refreshPromise = null;
      sessionStorage.removeItem(key);
      removeLegacy();
      window.dispatchEvent(new Event("hub-session-cleared"));
    },
  });
})();
