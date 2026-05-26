class Box {
  #value;

  constructor(value) {
    this.#value = value;
  }

  bump(step = 1) {
    this.#value += step;
    return this.#value;
  }
}

const box = new Box(3);
box.bump(4);
