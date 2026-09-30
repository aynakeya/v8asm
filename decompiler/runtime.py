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
function to_numeric(value) {
  if (isJSReceiver(value)) {
    const exotic = value[Symbol.toPrimitive];
    if (exotic !== undefined && exotic !== null) {
      value = Reflect.apply(exotic, value, ["number"]);
    } else {
      for (const name of ["valueOf", "toString"]) {
        const method = value[name];
        if (typeof method !== "function") continue;
        const primitive = Reflect.apply(method, value, []);
        if (!isJSReceiver(primitive)) {
          value = primitive;
          break;
        }
      }
    }
    if (isJSReceiver(value)) throw new TypeError("Cannot convert object to primitive value");
  }
  return typeof value === "bigint" ? value : +value;
}
function delete_property_strict(object, key) {
  "use strict";
  return delete object[key];
}
function create_array_literal(v) { return Array.isArray(v) ? v.slice() : []; }
function create_object_literal(v) { return v && typeof v === "object" ? { ...v } : {}; }
function create_closure(fn) { return typeof fn === "function" ? fn : function () { return undefined; }; }
function create_unmapped_arguments() {
  "use strict";
  return arguments;
}
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
function checked_lexical(value, name) {
  if (value === HOLE) {
    throw new ReferenceError("Cannot access '" + name + "' before initialization");
  }
  return value;
}
function ThrowIteratorResultNotAnObject(v) {
  throw new TypeError("Iterator result is not an object: " + String(v));
}
function DefineAccessorPropertyUnchecked(receiver, key, getter, setter, attributes) {
  const descriptor = {
    enumerable: !(attributes & 2),
    configurable: !(attributes & 4),
  };
  if (getter !== null) descriptor.get = getter;
  if (setter !== null) descriptor.set = setter;
  Object.defineProperty(receiver, key, descriptor);
}
function DefineGetterPropertyUnchecked(receiver, key, getter, attributes) {
  if (getter.name === "") set_function_name(getter, key, "get ");
  DefineAccessorPropertyUnchecked(receiver, key, getter, null, attributes);
}
function DefineSetterPropertyUnchecked(receiver, key, setter, attributes) {
  if (setter.name === "") set_function_name(setter, key, "set ");
  DefineAccessorPropertyUnchecked(receiver, key, null, setter, attributes);
}
function ToName(value) {
  return Reflect.ownKeys({ [value]: 0 })[0];
}
function set_function_name(fn, key, prefix = "") {
  const name = typeof key === "symbol"
    ? (key.description === undefined ? "" : "[" + key.description + "]")
    : String(key);
  Object.defineProperty(fn, "name", { value: prefix + name, configurable: true });
}
function define_literal_property(target, key, value, setName, enumerable) {
  if (setName) set_function_name(value, key);
  Object.defineProperty(target, key, {
    value, writable: true, enumerable, configurable: true,
  });
}
function ThrowPatternAssignmentNonCoercible() {
  throw new TypeError("Cannot destructure null or undefined");
}
function CopyDataProperties(target, source, excluded = []) {
  if (source === null || source === undefined) return;
  const object = Object(source);
  for (const key of Reflect.ownKeys(object)) {
    if (excluded.includes(key)) continue;
    const descriptor = Object.getOwnPropertyDescriptor(object, key);
    if (descriptor && descriptor.enumerable) {
      Object.defineProperty(target, key, {
        value: object[key], writable: true, enumerable: true, configurable: true,
      });
    }
  }
}
function CopyDataPropertiesWithExcludedPropertiesOnStack(source, ...keys) {
  if (source === null || source === undefined) ThrowPatternAssignmentNonCoercible();
  const out = {};
  CopyDataProperties(out, source, keys);
  return out;
}
'''
