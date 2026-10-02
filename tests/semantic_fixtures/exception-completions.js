function completion(mode, events) {
  try {
    if (mode === 0) return 7;
    if (mode === 1) throw 8;
    events[events.length] = "body";
  } finally {
    events[events.length] = "cleanup-event";
    if (mode === 1) return 9;
    if (mode === 3) throw 10;
  }
  return 11;
}
function directReturn(events) {
  try { return events.length + 30; }
  finally { events[events.length] = "direct-return"; }
}
function normalCompletion(events) {
  try { events[events.length] = "normal-body"; }
  finally { events[events.length] = "normal-cleanup"; }
}
function loopCompletion() {
  const events = [];
  for (let index = 0; index < 4; index++) {
    try {
      if (index === 1) continue;
      if (index === 2) break;
      events[events.length] = index;
    } finally { events[events.length] = "cleanup-event"; }
  }
  return events;
}
function nestedCompletion() {
  const events = [];
  try {
    try { throw 12; }
    finally { events[events.length] = "inner"; }
  } catch (error) { events[events.length] = error; }
  finally { events[events.length] = "outer"; }
  try { throw 13; } catch (error) { events[events.length] = error; }
  return events;
}
function iteratorCompletion(mode) {
  const events = [];
  const iteratorSuffix = "ator";
  const iterable = {
    [Symbol["iter" + iteratorSuffix]]() { return this; },
    next() { return { value: 21, done: false }; },
    return() { events[events.length] = "iterator-closed"; return {}; },
  };
  try {
    for (const value of iterable) {
      events[events.length] = value;
      if (mode) throw 22;
      break;
    }
  } catch (error) { events[events.length] = error; }
  return events;
}
function destructuredCatch() {
  const e = "outer";
  let result;
  function fail() { throw { code: 7, message: "failed" }; }
  try { fail(); }
  catch ({ code, message }) { result = [code, message, e]; }
  return result;
}
function run() {
  const events = [];
  const results = [completion(0, events), completion(1, events), completion(2, events)];
  try { completion(3, events); } catch (error) { results[3] = error; }
  results[4] = directReturn(events);
  normalCompletion(events);
  return [results, events, loopCompletion(), nestedCompletion(), iteratorCompletion(0), iteratorCompletion(1), destructuredCatch()];
}
globalThis.__semantic_result = run();
