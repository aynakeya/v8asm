function recover(shouldThrow) {
  let state = 2;
  try {
    if (shouldThrow) {
      throw 7;
    }
    state += 3;
  } catch (error) {
    state += error;
  }
  return state;
}

globalThis.__semantic_result = {
  normal: recover(false),
  thrown: recover(true),
};
