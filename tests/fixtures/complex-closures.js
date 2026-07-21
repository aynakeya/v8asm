function createCounter(start = 0) {
  let value = start;
  return {
    increment(step = 1) {
      value += step;
      return value;
    },
    read: () => value,
  };
}

function mapValues(items, transform) {
  const result = [];
  for (const item of items) {
    if (item?.enabled) {
      result.push(transform(item.value ?? 0));
    }
  }
  return result;
}

const counter = createCounter(2);
const output = mapValues(
  [
    { enabled: true, value: 3 },
    { enabled: false, value: 8 },
    { enabled: true },
  ],
  (value) => counter.increment(value),
);

globalThis.result = { output, current: counter.read() };
