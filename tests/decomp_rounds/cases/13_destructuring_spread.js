function collect(input) {
  const { a = 1, b, ...rest } = input;
  const values = [a, b, ...Object.values(rest)];
  let total = 0;
  for (const value of values) {
    total += value;
  }
  return total;
}
collect({ b: 2, c: 3, d: 4 });
