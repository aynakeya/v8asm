function runFlow(shouldThrow) {
  let state = 1;
  try {
    state += 2;
    if (shouldThrow) {
      throw 5;
    }
    state += 4;
    return state;
  } catch (error) {
    state += error;
    return state;
  } finally {
    globalThis.__finally_count += 1;
  }
}

globalThis.__finally_count = 0;
globalThis.__semantic_result = {
  normal: runFlow(false),
  thrown: runFlow(true),
  finallyCount: globalThis.__finally_count,
};
