def runtime_prelude() -> str:
    return '''const HOLE = Symbol("hole");
const __v8ctx = { slots: [] };
const context_slot = __v8ctx.slots;
const script_context = __v8ctx.slots;
let context = null;
let closure = undefined;

function truthy(v) { return !!v; }
function isNullish(v) { return v === null || v === undefined; }
function isJSReceiver(v) {
  const t = typeof v;
  return (t === "object" && v !== null) || t === "function";
}
function create_array_literal(v) { return Array.isArray(v) ? v.slice() : []; }
function create_object_literal(v) { return v && typeof v === "object" ? { ...v } : {}; }
function create_closure(fn) { return typeof fn === "function" ? fn : function () { return undefined; }; }
function create_function_context(scope, slots) { return { scope, slots: new Array(Number(slots) || 0) }; }
function create_block_context(scope) { return { scope, slots: [] }; }
function create_catch_context(value, scope) { return { value, scope, slots: [value] }; }
function pushContext(v) {
  const prev = context;
  context = v;
  return prev;
}
function GetIterator(v) { return v[Symbol.iterator](); }
function DeclareGlobals() { return undefined; }
function ensureDefined(name) {
  if (!(name in globalThis) && context_slot[name] === HOLE) {
    throw new ReferenceError(String(name));
  }
}
function ThrowIteratorResultNotAnObject(v) {
  throw new TypeError("Iterator result is not an object: " + String(v));
}
function _CopyDataPropertiesWithExcludedPropertiesOnStack(source, ...keys) {
  const out = {};
  for (const key of Object.keys(Object(source))) {
    if (!keys.includes(key)) out[key] = source[key];
  }
  return out;
}
'''
