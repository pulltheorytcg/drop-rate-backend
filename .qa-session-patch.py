from pathlib import Path
ROOT=Path('.')
def change(path,old,new):
 p=ROOT/path;s=p.read_text();assert s.count(old)==1,(path,s.count(old),old[:80]);p.write_text(s.replace(old,new))
change('backend/app/static/hub-session.js','  let refreshPromise = null;','  let refreshPromise = null;\n  let sessionEpoch = 0;')
change('backend/app/static/hub-session.js','''    refresh(task) {
      if (!refreshPromise) refreshPromise = Promise.resolve().then(task).finally(() => { refreshPromise = null; });
      return refreshPromise;
    },''','''    capture(getSession) {
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
    },''')
change('backend/app/static/hub-session.js','''    save(session) {
      removeLegacy();
      sessionStorage.setItem(key, JSON.stringify(session));
    },
    clear() {
      sessionStorage.removeItem(key);''','''    save(session) {
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
      sessionStorage.removeItem(key);''')
for path in ('backend/app/static/app.js','backend/app/static/owner-portal.js'):
 change(path,'''async function hydrateSessionUser() {
  if (!state.session?.access_token) return;
  const user = await authRequest("/user", {
    headers: {Authorization: `Bearer ${state.session.access_token}`},
  });
  state.session.user = user;
  saveSession(state.session);
}''','''async function hydrateSessionUser() {
  if (!state.session?.access_token) return;
  const checkSession = window.PullTheoryHubSession.capture(() => state.session);
  try {
    const user = await authRequest("/user", {
      headers: {Authorization: `Bearer ${state.session.access_token}`},
    });
    checkSession();
    state.session.user = user;
    saveSession(state.session);
  } catch (error) { checkSession(); throw error; }
}''')
 change(path,'''async function refreshSession() {
  return window.PullTheoryHubSession.refresh(async () => {
    const previous = state.session;
    try {''','''async function refreshSession() {
  const previous = state.session;
  const checkSession = window.PullTheoryHubSession.capture(() => state.session);
  return window.PullTheoryHubSession.refresh(async () => {
    try {
      checkSession();''')
 change(path,'''      if (state.session !== previous) throw new Error("Your account changed. Please sign in again.");
      saveSession(session);''','''      checkSession();
      if (session.user?.id && previous.user?.id && session.user.id !== previous.user.id) {
        throw new Error("Your account changed. Please sign in again.");
      }
      if (!session.user && previous.user) session.user = previous.user;
      saveSession(session);''')
 change(path,'''    } catch (error) {
      error.refreshSession = previous;''','''    } catch (error) {
      checkSession();
      error.refreshSession = previous;''')
 p=ROOT/path;s=p.read_text();start=s.index('async function apiRequest(');end=s.index('\n}\n',start)+3
 s=s[:start]+'''async function apiRequest(path, options = {}, retry = true) {
  const checkSession = window.PullTheoryHubSession.capture(() => state.session);
  checkSession();
  const requestOptions = {
    ...options,
    headers: {"Content-Type": "application/json", ...(options.headers || {}), Authorization: `Bearer ${state.session.access_token}`},
  };
  try {
    let response = await fetch(path, requestOptions);
    checkSession();
    if (response.status === 401 && retry) {
      requestOptions.headers.Authorization = `Bearer ${await refreshSession()}`;
      checkSession();
      response = await fetch(path, requestOptions);
      checkSession();
    }
    const data = await readJson(response);
    checkSession();
    return data;
  } catch (error) { checkSession(); throw error; }
}
''' + s[end:];p.write_text(s)
p=ROOT/'backend/app/static/app.js';s=p.read_text();start=s.index('async function apiImageBlob(');end=s.index('\n}\n',start)+3
s=s[:start]+'''async function apiImageBlob(path, retry = true) {
  const checkSession = window.PullTheoryHubSession.capture(() => state.session);
  checkSession();
  const requestOptions = {headers: {Authorization: `Bearer ${state.session.access_token}`}};
  try {
    let response = await fetch(path, requestOptions);
    checkSession();
    if (response.status === 401 && retry) {
      requestOptions.headers.Authorization = `Bearer ${await refreshSession()}`;
      checkSession();
      response = await fetch(path, requestOptions);
      checkSession();
    }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      checkSession();
      throw new Error(errorMessage(data));
    }
    const blob = await response.blob();
    checkSession();
    return blob;
  } catch (error) { checkSession(); throw error; }
}
''' + s[end:];p.write_text(s)
change('backend/app/static/owner-portal.js','''  state.inventory.requestRevision = (state.inventory.requestRevision || 0) + 1;
  window.DropRateInventory?.reset();''','''  state.inventory.requestRevision = (state.inventory.requestRevision || 0) + 1;
  state.channels.requestRevision = (state.channels.requestRevision || 0) + 1;
  state.ownerChannelAccount = null;
  state.ownerChannelSummaries = [];
  state.financeSummary = null;
  state.payoutPreference = null;
  state.profile = null;
  window.DropRateInventory?.reset();''')
change('backend/app/static/owner-inventory.js','''    let suggestionPrefilled = item.store_price_minor == null && recommended != null;
    priceInput.addEventListener("input", () => { suggestionPrefilled = false; });''','''    let suggestionPrefilled = item.store_price_minor == null && recommended != null;
    let priceEdited = false;
    const recommendationText = recommendationNote.textContent;
    priceInput.addEventListener("input", () => { suggestionPrefilled = false; priceEdited = true; });''')
change('backend/app/static/owner-inventory.js','''      if (!sameBasis) recommendationNote.textContent = "Recorded-condition recommendation does not apply to the newly selected condition.";''','''      recommendationNote.textContent = sameBasis ? recommendationText
        : "Recorded-condition recommendation does not apply to the newly selected condition.";
      if (sameBasis && !priceEdited && item.store_price_minor == null && recommended != null) {
        priceInput.value = (recommended / 100).toFixed(2);
        suggestionPrefilled = true;
      }''')
