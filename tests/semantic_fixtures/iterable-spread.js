function copy(value) { return [...value]; }
function spreadTrace(mode) {
  const events = [];
  const suffix = "ator";
  const source = {
    get [Symbol["iter" + suffix]]() {
      events[events.length] = "get-iterator";
      if (mode === "iterator-error") throw new Error("iterator");
      return function () {
        events[events.length] = "call-iterator";
        let index = 0;
        return {
          get next() {
            events[events.length] = "get-next";
            return function () {
              const current = index++;
              events[events.length] = "next:" + current;
              if (mode === "next-error") throw new Error("next");
              if (mode === "bad-result") return 1;
              return {
                get done() {
                  events[events.length] = "done:" + current;
                  if (mode === "done-error") throw new Error("done");
                  return current === 2;
                },
                get value() {
                  events[events.length] = "value:" + current;
                  if (mode === "value-error") throw new Error("value");
                  return current + 10;
                }
              };
            };
          },
          return() { events[events.length] = "closed"; return {}; }
        };
      };
    }
  };
  try { return { copiedValues: copy(source), events }; }
  catch (error) { return { error: error.name, events }; }
}
function run() {
  const source = [1, 2];
  const duplicate = copy(source);
  duplicate[0] = 9;
  const sparse = new Array(2);
  const dense = copy(sparse);
  let invalid;
  try { copy(null); } catch (error) { invalid = error.name; }
  return {
    source, duplicate, fresh: source !== duplicate,
    set: copy(new Set([1, 2, 1])), text: copy("a\ud83d\ude00b"),
    dense: [dense.length, 0 in sparse, 0 in dense, dense[0] === undefined], invalid,
    traces: [spreadTrace("normal"), spreadTrace("iterator-error"), spreadTrace("next-error"),
      spreadTrace("bad-result"), spreadTrace("done-error"), spreadTrace("value-error")]
  };
}
globalThis.__semantic_result = run();
