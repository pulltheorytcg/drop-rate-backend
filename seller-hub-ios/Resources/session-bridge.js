/* Installed at document start, main frame only, by the native app. */
(function (bootstrap) {
  'use strict';
  if (location.origin !== 'https://drop-rate-api-live-production.up.railway.app' || window.top !== window) return;
  const key = 'drop_rate_hub_session';
  const bootstrapped = 'drop_rate_native_session_bootstrapped';
  const proto = Storage.prototype;
  const get = proto.getItem;
  const set = proto.setItem;
  const remove = proto.removeItem;
  const clear = proto.clear;
  // postMessage is asynchronous. A logout followed by immediate navigation must
  // not re-seed an older native snapshot while its clear message is in flight.
  if (!get.call(sessionStorage, bootstrapped)) {
    if (bootstrap && !get.call(sessionStorage, key)) {
      set.call(sessionStorage, key, JSON.stringify(bootstrap));
    }
    set.call(sessionStorage, bootstrapped, '1');
  }
  function publish() {
    window.webkit.messageHandlers.hubSession.postMessage({
      type: 'session', value: get.call(sessionStorage, key),
    });
  }
  proto.setItem = function (name, value) {
    set.call(this, name, value);
    if (this === sessionStorage && String(name) === key) publish();
  };
  proto.removeItem = function (name) {
    remove.call(this, name);
    if (this === sessionStorage && String(name) === key) publish();
  };
  proto.clear = function () {
    clear.call(this);
    if (this === sessionStorage) {
      set.call(sessionStorage, bootstrapped, '1');
      publish();
    }
  };
  window.addEventListener('hub-session-cleared', publish);
})(__DROP_RATE_BOOTSTRAP__);
