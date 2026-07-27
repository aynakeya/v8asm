function runCallOrder() {
  const semanticEvents = [];
  let traceIndex = 0;

  function mark(label, value) {
    semanticEvents[traceIndex] = label;
    traceIndex += 1;
    return value;
  }

  const receiver = {
    base: 10,
    add(value) {
      semanticEvents[traceIndex] = "method";
      traceIndex += 1;
      return this.base + value;
    },
  };

  const key = mark("key", "add");
  const value = receiver[key](mark("argument", 5));
  return { value, semanticEvents };
}

globalThis.__semantic_result = runCallOrder();
