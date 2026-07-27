function calculate(a, b, c) {
  let value = a + b;
  value += c;
  return value * 2;
}

globalThis.__semantic_result = calculate(1, 2, 3);
