class Counter {
  constructor(n) {
    this.n = n;
  }

  inc(step = 1) {
    this.n += step;
    return this.n;
  }
}

const counter = new Counter(2);
counter.inc(3);
