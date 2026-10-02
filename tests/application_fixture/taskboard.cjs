const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

// This VM runs only the local fixture and its recovered output, not untrusted code.
function observe(source, scenario, commands = []) {
  const sandbox = { __scenario: scenario, __commands: commands };
  vm.createContext(sandbox, { microtaskMode: "afterEvaluate" });
  try {
    vm.runInContext(source, sandbox, { timeout: 2000, filename: "taskboard.js" });
    vm.runInContext(`
      function encode(value) {
        return JSON.stringify(value, (_key, item) => {
          if (item === undefined) return { $type: "undefined" };
          if (typeof item === "bigint") return { $type: "bigint", value: String(item) };
          if (typeof item === "number" && (!Number.isFinite(item) || Object.is(item, -0))) {
            return { $type: "number", value: Object.is(item, -0) ? "-0" : String(item) };
          }
          return item;
        });
      }
      globalThis.__observation = encode({ status: "pending" });
      Promise.resolve(globalThis.taskboard(__scenario, __commands)).then(
        value => { globalThis.__observation = encode({ status: "ok", value }); },
        error => { globalThis.__observation = encode({
          status: "throw", name: error.name, message: error.message,
        }); }
      );
    `, sandbox, { timeout: 2000, filename: "observe-taskboard.js" });
    return JSON.parse(sandbox.__observation);
  } catch (error) {
    return {
      status: error.code === "ERR_SCRIPT_EXECUTION_TIMEOUT" ? "timeout" : "throw",
      name: error.name, message: error.message,
    };
  }
}

if (require.main === module) {
  const args = process.argv.slice(2);
  let result;
  if (args[0] === "--observe") {
    const { source, scenario, commands } = JSON.parse(fs.readFileSync(0, "utf8"));
    result = observe(source, scenario, commands);
  } else {
    const source = fs.readFileSync(path.join(__dirname, "taskboard.js"), "utf8");
    result = args[0] === "--case"
      ? observe(source, args[1])
      : observe(source, args.length ? "commands" : "workflow", args);
  }
  process.stdout.write(JSON.stringify(result, null, 2) + "\n");
  process.exitCode = result.status === "ok" ? 0 : 1;
}

module.exports = { observe };
