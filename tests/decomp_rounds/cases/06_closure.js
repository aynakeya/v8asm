function makeAdder(base) {
  return function add(x) {
    return base + x;
  };
}
const add5 = makeAdder(5);
add5(9);
