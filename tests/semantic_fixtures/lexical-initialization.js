function captureValue(read) {
  try {
    return { value: read() };
  } catch (error) {
    return { error: error.name, message: error.message };
  }
}

function readMissingType() { return typeof missingForTypeofFixture; }
function testMissingType() { return typeof missingForTypeofFixture === "undefined"; }
function readThrowingType() { return typeof throwingTypeofFixture; }
function readRegisterTDZ() {
  const result = registerLocal;
  let registerLocal = 5;
  return result;
}
function readScriptLater() { return scriptLater; }
function readScriptType() { return typeof scriptLater; }

function runLexicalInitialization() {
  function readLater() { return later; }
  function readUndefined() { return intentionallyUndefined; }
  function readType() { return typeof later; }
  const before = captureValue(readLater);
  const typeBefore = captureValue(readType);
  const missingType = readMissingType();
  const missingTest = testMissingType();
  let later = 7;
  let intentionallyUndefined;
  const after = captureValue(readLater);
  const typeAfter = captureValue(readType);
  const undefinedValue = captureValue(readUndefined);
  later = 11;
  Object.defineProperty(globalThis, "throwingTypeofFixture", {
    get() { throw new ReferenceError("typeof getter ran"); },
    configurable: true
  });
  const getterFailure = captureValue(readThrowingType);
  return { before, typeBefore, after, typeAfter, undefinedValue,
    hasUndefinedValue: "value" in undefinedValue, updated: readLater(),
    missingType, missingTest, getterFailure };
}

const scriptBefore = captureValue(readScriptLater);
const scriptTypeBefore = captureValue(readScriptType);
let scriptLater = 13;
const scriptAfter = captureValue(readScriptLater);
globalThis.__semantic_result = {
  local: runLexicalInitialization(),
  secondRun: runLexicalInitialization(),
  registerBefore: captureValue(readRegisterTDZ),
  scriptBefore, scriptTypeBefore, scriptAfter
};
