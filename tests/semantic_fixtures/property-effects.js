function runPropertyEffects() {
  const events = [];
  let eventIndex = 0;
  let value = 3;
  const holder = {
    get observedValue() {
      events[eventIndex] = value;
      eventIndex += 1;
      return value;
    },
  };

  holder.observedValue;
  const before = holder.observedValue;
  value = 9;
  return {
    before,
    after: holder.observedValue,
    events,
  };
}

function runPropertyDefault(input, failGet, failFallback) {
  const events = [];
  let reads = 0;
  const holder = {
    get observedValue() {
      events[events.length] = "property-read";
      reads++;
      if (failGet) throw "property-failed";
      return reads === 1 ? input : 99;
    },
  };
  function fallback() {
    events[events.length] = "default-called";
    if (failFallback) throw "default-failed";
    return 7;
  }
  try {
    const { observedValue = fallback() } = holder;
    return { value: observedValue, reads, events };
  } catch (error) {
    return { error, reads, events };
  }
}

function runReferenceUpdate(mode) {
  const events = [];
  const items = [{ amount: 1 }, { amount: 2 }];
  let reads = 0;
  const source = {
    get child() {
      events[events.length] = "child-read";
      return items[reads++ % 2];
    },
  };
  let holder = items[0];
  function swap() {
    events[events.length] = "holder-changed";
    holder = items[1];
    return 3;
  }
  if (mode === 0) {
    source.child.amount = source.child.amount + 3;
  } else if (mode === 1) {
    source.child.amount += 3;
  } else if (mode === 2) {
    const value = source.child.amount + 3;
    source.child.amount = value;
  } else {
    const value = holder.amount + swap();
    holder.amount = value;
  }
  return { first: items[0].amount, second: items[1].amount, reads, events };
}

globalThis.__semantic_result = {
  reads: runPropertyEffects(),
  defined: runPropertyDefault(3, false, false),
  zero: runPropertyDefault(0, false, false),
  nullValue: runPropertyDefault(null, false, false),
  absent: runPropertyDefault(undefined, false, false),
  getterThrows: runPropertyDefault(undefined, true, false),
  fallbackThrows: runPropertyDefault(undefined, false, true),
  repeatedReference: runReferenceUpdate(0),
  compoundReference: runReferenceUpdate(1),
  savedReference: runReferenceUpdate(2),
  replacedReceiver: runReferenceUpdate(3),
};
