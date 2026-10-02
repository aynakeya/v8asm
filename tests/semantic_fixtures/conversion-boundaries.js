function render(value) {
  try {
    return { value: `prefix:${value}:suffix` };
  } catch (error) {
    return { error: error.name };
  }
}
function Empty() { this.count = arguments.length; }
function number(value) {
  try {
    const result = +value;
    return [typeof result, String(result), result === 0 && 1 / result === -Infinity];
  } catch (error) {
    return [error.name];
  }
}
function negative(value) {
  try {
    const result = -value;
    return [typeof result, String(result)];
  } catch (error) { return [error.name]; }
}
function runConversions() {
  const events = [];
  let index = 0;
  const primitiveSuffix = "Primitive";
  const object = {
    [Symbol["to" + primitiveSuffix]](hint) {
      events[index] = hint;
      index += 1;
      return "converted";
    }
  };
  const fallback = {
    valueOf() { events[index++] = "valueOf"; return {}; },
    toString() { events[index++] = "toString"; return "21"; }
  };
  return {
    object: render(object), symbol: render(Symbol("input")),
    bigint: render(BigInt(17)), empty: new Empty().count,
    argument: new Empty(3).count,
    numbers: [number("37.25"), number("-0"), number(undefined), number(null),
      number(false), number(BigInt(17)), number(Symbol("number")), number(object),
      number(fallback), number({ valueOf() { return BigInt(2); } })],
    negatives: [negative("37.25"), negative(BigInt(17)), negative(Symbol("negative")), negative(fallback)], events
  };
}
globalThis.__semantic_result = runConversions();
