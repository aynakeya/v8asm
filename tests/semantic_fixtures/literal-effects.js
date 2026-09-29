function runLiteralEffects() {
  const events = [];
  let index = 0;
  function mark(value) {
    events[index] = value;
    index += 1;
    return value;
  }
  Object.defineProperty(Object.prototype, "added", {
    set(value) { mark("prototype setter"); },
    configurable: true
  });
  const source = {
    get first() { return mark(3); },
    get second() { return mark(5); }
  };
  const key = { toString() { return mark("computed"); } };
  const copy = { ...source, added: mark(7), [key]: mark(11) };
  const pair = {
    get value() { return index; },
    set value(value) { mark(value); },
    method(value) { return this.value + value; },
    regular: function regular(value) { return value; }
  };
  pair.value = 17;
  const nested = { empty: [], rows: [{ items: [] }, { items: [1, 2] }] };
  const nullEmpty = { __proto__: null };
  const nullPopulated = { __proto__: null, ownValue: 31 };
  const nullNested = { emptyValue: { __proto__: null }, fullValue: { __proto__: null, ownValue: 37 } };
  nested.empty[0] = 23;
  nested.rows[0].items[0] = 29;
  const descriptor = Object.getOwnPropertyDescriptor(pair, "value");
  return {
    first: copy.first,
    second: copy.second,
    added: copy.added,
    computed: copy.computed,
    getterName: descriptor.get.name,
    setterName: descriptor.set.name,
    enumerable: descriptor.enumerable,
    configurable: descriptor.configurable,
    methodName: pair.method.name,
    methodHasPrototype: "prototype" in pair.method,
    regularHasPrototype: "prototype" in pair.regular,
    methodResult: pair.method(19),
    nested: nested,
    sharedEmpty: nested.empty === nested.rows[0].items,
    emptyInherits: nullEmpty instanceof Object,
    populatedInherits: nullPopulated instanceof Object,
    nestedEmptyInherits: nullNested.emptyValue instanceof Object,
    nestedFullInherits: nullNested.fullValue instanceof Object,
    inheritedMethod: "toString" in nullEmpty,
    ownValue: nullPopulated.ownValue,
    nestedOwnValue: nullNested.fullValue.ownValue,
    events: events
  };
}
globalThis.__semantic_result = runLiteralEffects();
