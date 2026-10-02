function classMembers(seed) {
  class Counter {
    constructor(value) { this.value = value + seed; }
    add(amount) { this.value += amount; return this.value; }
    get current() { return this.value; }
    set current(value) { this.value = value; }
    identity() { return Counter; }
    receiver() { return this; }
    static category() { return "counter-kind"; }
  }
  const counter = new Counter(2);
  const first = counter.add(3);
  counter.current = 17;
  const detached = counter.receiver;
  const descriptor = Object.getOwnPropertyDescriptor(Counter.prototype, "current");
  const namesSuffix = "Names";
  let callError;
  let constructError;
  try { Counter(1); } catch (error) { callError = error.name; }
  try { new counter.add(1); } catch (error) { constructError = error.name; }
  return [first, counter.current, counter.identity() === Counter,
          counter instanceof Counter, detached() === undefined,
          Counter.name, Counter.length, counter.add.name, counter.add.length,
          descriptor.enumerable, descriptor.configurable,
          descriptor.get.name, descriptor.set.name,
          Object.keys(Counter.prototype), Object["getOwnProperty" + namesSuffix](Counter.prototype),
          Counter.category(), callError, constructError];
}
function defaultConstructor() {
  class Empty { answer() { return 42; } }
  return new Empty().answer();
}
globalThis.__semantic_result = [classMembers(5), classMembers(10), defaultConstructor()];
