function canConstruct(fn) {
  try {
    new fn(0);
    return true;
  } catch (error) {
    return false;
  }
}

function counter() {
  let next = 0;
  return { next() { return ++next; }, current() { return next; } };
}

function runObjectMembers() {
  const events = [];
  let index = 0;
  let stored = 3;
  function mark(value) {
    events[index] = value;
    index += 1;
    return value;
  }
  const key = { toString() { return mark("value"); } };
  function makeKey() { return mark("computed"); }
  const symbol = Symbol("accessor");
  const methods = {
    "some-key"() { return 7; },
    17() { return 11; },
    ordinary: function ordinary() { return 13; }
  };
  const pair = {
    get [key]() { return mark(stored); },
    set [key](value) { stored = mark(value); },
    get [symbol]() { return stored + 1; },
    set [symbol](value) { stored = value - 1; }
  };
  const afterSpread = { ...{ first: 1 }, get value() { return 19; } };
  const calledKey = {
    get [makeKey()]() { return stored; },
    set [makeKey()](value) { stored = value; }
  };
  const duplicate = {
    method() { return 1; },
    method() { return 2; }
  };
  const replacement = {
    get value() { return 1; },
    value: 2,
    set value(value) { this.saved = value; }
  };
  replacement.value = 31;
  calledKey.computed = 3;
  const before = pair.value;
  pair.value = 23;
  const after = pair.value;
  pair[symbol] = 30;
  const descriptor = Object.getOwnPropertyDescriptor(pair, "value");
  const symbolDescriptor = Object.getOwnPropertyDescriptor(pair, symbol);
  const calledDescriptor = Object.getOwnPropertyDescriptor(calledKey, "computed");
  const iterator = counter();
  return {
    counter: [iterator.next(), iterator.next(), iterator.current(), iterator.next.name],
    quoted: methods["some-key"](),
    numeric: methods[17](),
    quotedName: methods["some-key"].name,
    numericName: methods[17].name,
    quotedConstructor: canConstruct(methods["some-key"]),
    numericConstructor: canConstruct(methods[17]),
    ordinaryConstructor: canConstruct(methods.ordinary),
    duplicateValue: duplicate.method(),
    duplicateConstructor: canConstruct(duplicate.method),
    replacedGetter: replacement.value === undefined,
    replacementSetter: replacement.saved,
    before, after, symbolValue: pair[symbol],
    getterConstructor: canConstruct(descriptor.get),
    setterConstructor: canConstruct(descriptor.set),
    calledGetterConstructor: canConstruct(calledDescriptor.get),
    calledSetterConstructor: canConstruct(calledDescriptor.set),
    calledValue: calledKey.computed,
    getterName: descriptor.get.name,
    setterName: descriptor.set.name,
    symbolGetterName: symbolDescriptor.get.name,
    symbolSetterName: symbolDescriptor.set.name,
    enumerable: descriptor.enumerable,
    configurable: descriptor.configurable,
    spreadValue: afterSpread.value,
    events
  };
}
globalThis.__semantic_result = runObjectMembers();
