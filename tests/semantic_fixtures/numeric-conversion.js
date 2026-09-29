function updateNumeric(value) {
  const before = value++;
  const after = ++value;
  const decrement = value--;
  return {
    beforeText: String(before),
    beforeType: typeof before,
    afterText: String(after),
    decrementText: String(decrement),
    finalText: String(value),
    negativeZero: typeof before === "number" && 1 / before === Number("-Infinity"),
  };
}

function readNumericFailure(value) {
  try {
    return { value: ++value };
  } catch (error) {
    return { error: error.name };
  }
}

function compoundNumeric(value) {
  const added = (value += 2);
  const multiplied = (value *= 3);
  return { value, added, multiplied };
}

function runNumericConversion() {
  const events = [];
  const primitiveSuffix = "Primitive";
  const primitiveKey = Symbol["to" + primitiveSuffix];
  const exotic = {
    [primitiveKey](hint) {
      events[events.length] = hint;
      return BigInt("17");
    },
  };
  const ordinary = {
    valueOf() {
      events[events.length] = "ordinary-value";
      return {};
    },
    toString() {
      events[events.length] = "ordinary-string";
      return "23";
    },
  };
  return {
    numberValue: updateNumeric(7),
    stringValue: updateNumeric("9"),
    bigintValue: updateNumeric(BigInt("11")),
    zeroValue: updateNumeric(Number("-0")),
    exoticValue: updateNumeric(exotic),
    ordinaryValue: updateNumeric(ordinary),
    compoundValue: compoundNumeric(5),
    symbolFailure: readNumericFailure(Symbol("invalid-numeric")),
    invalidPrimitive: readNumericFailure({ [primitiveKey]() { return {}; } }),
    events,
  };
}

globalThis.__semantic_result = runNumericConversion();
