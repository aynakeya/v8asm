function runObjectRestSpread() {
  const events = [];
  let index = 0;
  const retainedSymbol = Symbol("retained");
  const excludedSymbol = Symbol("excluded");

  function mark(value) {
    events[index] = value;
    index += 1;
    return value;
  }

  const source = {
    get alphaValue() {
      mark("alpha");
      return 3;
    },
    get betaValue() {
      mark("beta");
      return 5;
    },
    [retainedSymbol]: 7,
    [excludedSymbol]: 11,
    ["__proto__"]: 13,
  };

  const selectionKey = {
    toString() {
      return mark("alphaValue");
    },
  };
  const { [selectionKey]: selected, [excludedSymbol]: omitted, ...rest } = source;
  const copy = { ...source, betaValue: mark(17), extraValue: 19 };
  const nullPrototype = { ...source, __proto__: null };
  const methods = {
    [retainedSymbol](value) {
      return value + 1;
    },
  };
  copy.alphaValue = 23;
  const empty = { ...null, ...undefined };
  const text = { ..."ab" };
  return {
    selected,
    omitted,
    restValue: rest.betaValue,
    restRetained: rest[retainedSymbol],
    restExcluded: excludedSymbol in rest,
    restProtoValue: rest["__proto__"],
    copied: copy.alphaValue,
    overwritten: copy.betaValue,
    copiedSymbol: copy[retainedSymbol],
    copyProtoValue: copy["__proto__"],
    normalPrototype: copy instanceof Object,
    nullPrototype: nullPrototype instanceof Object,
    computedCall: methods[retainedSymbol](2),
    computedName: methods[retainedSymbol].name,
    sourceValue: source.alphaValue,
    empty,
    firstCharacter: text[0],
    secondCharacter: text[1],
    events,
  };
}

globalThis.__semantic_result = runObjectRestSpread();
