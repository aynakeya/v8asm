function runOptionalNullish() {
  const events = [];
  let index = 0;

  function mark(value) {
    events[index] = value;
    index += 1;
    return value;
  }

  function probe(holder) {
    return holder?.[mark("method")]?.(mark(3)) ?? mark("fallback");
  }

  function invoke(value) {
    return this.base + value;
  }

  const holder = {
    base: 4,
    get method() {
      mark("get");
      return invoke;
    },
  };
  const missingObject = probe(null);
  const missingMethod = probe({});
  const present = probe(holder);

  function coalesce(value) {
    return value ?? mark("default");
  }

  return {
    missingObject,
    missingMethod,
    present,
    zero: coalesce(0),
    falseValue: coalesce(false),
    empty: coalesce(""),
    nullValue: coalesce(null),
    undefinedValue: coalesce(undefined),
    events,
  };
}

globalThis.__semantic_result = runOptionalNullish();
