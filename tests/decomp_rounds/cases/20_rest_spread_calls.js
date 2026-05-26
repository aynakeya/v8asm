function collect(prefix, ...items) {
  return prefix + ':' + items.join(',');
}

class Pair {
  constructor(left, right) {
    this.left = left;
    this.right = right;
  }

  sum() {
    return this.left + this.right;
  }
}

function run(input) {
  const values = [input, input + 1];
  const pair = new Pair(...values);
  const bound = collect.call(null, 'v', ...values);
  return collect('x', ...values) + ':' + bound + ':' + Math.max(...values) + ':' + pair.sum();
}

run(4);
