function runDefaultRestSpread() {
  let defaults = 0;

  function defaultValue() {
    defaults += 1;
    return 5;
  }

  const holder = {
    base: 10,
    collect(first = defaultValue(), ...rest) {
      return {
        value: this.base + first,
        rest,
        argumentCount: arguments.length,
      };
    },
  };
  const values = [2, 3];
  const omitted = holder.collect();
  const explicitUndefined = holder.collect(undefined, ...values);
  const zero = holder.collect(0, ...values);
  const nullValue = holder.collect(null);

  function strictArguments(value) {
    "use strict";
    value = 9;
    const original = arguments[0];
    arguments[0] = 12;
    return { original, parameterAfterWrite: value, arrayInstance: arguments instanceof Array };
  }

  return {
    omitted,
    explicitUndefined,
    zero,
    nullValue,
    defaults,
    unmapped: strictArguments(3),
  };
}

globalThis.__semantic_result = runDefaultRestSpread();
