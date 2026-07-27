function runContextDepth(start) {
  let value = start;
  let outerBias = start + 1;

  function middle(innerStart) {
    let value = innerStart * 2;

    function read(delta) {
      return outerBias + value + delta;
    }

    return read(1);
  }

  return { inner: middle(3), outer: value };
}

globalThis.__semantic_result = runContextDepth(4);
