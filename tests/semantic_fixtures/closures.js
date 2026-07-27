function createCounter(start) {
  let value = start;

  function step(delta) {
    const before = value;
    value += delta;
    return { before, after: value };
  }

  const first = step(2);
  const second = step(3);
  return { first, second, final: value };
}

globalThis.__semantic_result = createCounter(4);
