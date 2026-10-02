/* One tab-scoped session for the two existing hubs. Authorization stays in /access/me. */
(function () {
  "use strict";
  const key = "drop_rate_hub_session";
  const legacyKeys = ["drop_rate_owner_session", "drop_rate_founder_session"];
  function removeLegacy() {
    legacyKeys.forEach(legacy => sessionStorage.removeItem(legacy));
  }
  window.PullTheoryHubSession = Object.freeze({
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
