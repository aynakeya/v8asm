function route(kind) {
  switch (kind) {
    case "add": return 1;
    case "done": return 2;
    case "list": return 3;
    default: return 4;
  }
}
function fallthrough(kind) {
  let result = "";
  switch (kind) {
    case "add": result += "entered-add;";
    case "done": result += "entered-done;"; break;
    default: result += "entered-default;";
    case "list": result += "entered-list;";
  }
  return result;
}
function run() {
  const results = [];
  const inputs = ["add", "done", "list", "other", 1, null];
  for (let index = 0; index < inputs.length; index++) {
    results[index] = [route(inputs[index]), fallthrough(inputs[index])];
  }
  return results;
}
globalThis.__semantic_result = run();
