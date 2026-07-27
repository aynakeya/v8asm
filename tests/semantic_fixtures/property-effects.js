function runPropertyEffects() {
  const events = [];
  let eventIndex = 0;
  let value = 3;
  const holder = {
    get observedValue() {
      events[eventIndex] = value;
      eventIndex += 1;
      return value;
    },
  };

  holder.observedValue;
  const before = holder.observedValue;
  value = 9;
  return {
    before,
    after: holder.observedValue,
    events,
  };
}

globalThis.__semantic_result = runPropertyEffects();
