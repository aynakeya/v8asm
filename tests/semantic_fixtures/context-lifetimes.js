function blockCaptures(seed) {
  const callbacks = [];
  { let value = seed; callbacks[0] = () => ++value; callbacks[1] = () => value; }
  { let value = seed + 10; callbacks[2] = () => value; }
  for (let index = 0; index < 3; index++) {
    callbacks[index + 3] = () => index;
  }
  return [callbacks[0](), callbacks[1](), callbacks[2](),
          callbacks[3](), callbacks[4](), callbacks[5]()];
}
function catchCaptures() {
  const callbacks = [];
  for (let index = 0; index < 2; index++) {
    try { throw index + 20; }
    catch (error) { callbacks[index] = () => error; }
  }
  return [callbacks[0](), callbacks[1]()];
}
function branchCaptures(flag) {
  let callback;
  if (flag) { let __proto__ = 3; callback = () => __proto__; }
  else { let value = 4; callback = () => value; }
  const callbacks = [];
  for (let index = 0; index < 5; index++) {
    if (index === 1) continue;
    if (index === 3) break;
    callbacks[callbacks.length] = () => index;
  }
  return [callback(), callback.name, callbacks[0](), callbacks[1]()];
}
function defaultCapture(seed = 3) {
  let value = seed;
  return { increment(amount = 1) { value += amount; return value; }, read: () => value };
}
const first = defaultCapture();
const second = defaultCapture(10);
globalThis.__semantic_result = [blockCaptures(2), blockCaptures(7), catchCaptures(),
  first.increment(), first.read(), second.increment(2), second.read(), first.read(),
  branchCaptures(true), branchCaptures(false)];
