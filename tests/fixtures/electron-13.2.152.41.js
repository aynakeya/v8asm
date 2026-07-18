function calc(a, b, c) {
  const x = a + b;
  return (x + c) * 2;
}
globalThis.answer = calc(1, 2, 3);
