function runShortCircuit() {
  let calls = 0;

  function bump(value) {
    calls += 1;
    return value;
  }

  const andValue = false && bump(1);
  const orValue = true || bump(2);
  const nullishValue = null ?? bump(3);
  const zeroValue = 0 ?? bump(4);
  return { andValue, orValue, nullishValue, zeroValue, calls };
}

globalThis.__semantic_result = runShortCircuit();
