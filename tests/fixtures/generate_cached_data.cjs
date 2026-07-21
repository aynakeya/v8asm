const fs = require("node:fs");
const vm = require("node:vm");

const [, , input, output] = process.argv;
if (!input || !output) {
  throw new Error("usage: node --no-lazy generate_cached_data.cjs INPUT OUTPUT");
}

const source = fs.readFileSync(input, "utf8");
const script = new vm.Script(source, { filename: input });
fs.writeFileSync(output, script.createCachedData());
