function runExpressionStatements() {
  let calls = 0;
  function nextObject() {
    calls += 1;
    return { value: calls };
  }
  ({ ...nextObject() });
  ({ ...nextObject() });
  nextObject() + 1;
  return calls;
}
globalThis.__semantic_result = runExpressionStatements();
