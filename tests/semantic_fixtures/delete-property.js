function strictDelete(object, key) {
  "use strict";
  return delete object[key];
}

function captureDelete(object, key) {
  try {
    return { value: strictDelete(object, key) };
  } catch (error) {
    return { error: error.name };
  }
}

function runDeleteProperty() {
  const events = [];
  const key = { toString() { events[events.length] = "key"; return "removable"; } };
  const object = { removable: 7, locked: 11 };
  Object.defineProperty(object, "locked", { configurable: false });
  const removed = delete object[key];
  const refused = delete object.locked;
  const strictRefused = captureDelete(object, "locked");
  const missing = strictDelete(object, "absent");
  const primitive = strictDelete(3, "absent");
  const nullFailure = captureDelete(null, "absent");
  const symbol = Symbol("delete-key");
  object[symbol] = 13;
  const symbolRemoved = strictDelete(object, symbol);
  const proxy = new Proxy({}, {
    deleteProperty(target, property) {
      events[events.length] = property;
      return false;
    },
  });
  return {
    removed,
    refused,
    strictRefused,
    missing,
    primitive,
    nullFailure,
    symbolRemoved,
    symbolPresent: symbol in object,
    remainingKeys: Object.keys(object),
    proxySloppy: delete proxy.silent,
    proxyStrict: captureDelete(proxy, "strict"),
    events,
  };
}

globalThis.__semantic_result = runDeleteProperty();
