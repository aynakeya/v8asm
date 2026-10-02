"use strict";

function tokenize(line) {
  const tokens = [];
  const pattern = /"((?:\\.|[^"\\])*)"|'([^']*)'|([^\s]+)/g;
  for (const match of line.matchAll(pattern)) {
    const [, quoted, single, bare] = match;
    tokens.push(quoted !== undefined ? JSON.parse(`"${quoted}"`) : single ?? bare);
  }
  return tokens;
}

function parseCommand(line) {
  const [command = "list", ...args] = tokenize(line);
  const options = Object.create(null);
  const positional = [];
  for (const arg of args) {
    if (!arg.startsWith("--")) {
      positional.push(arg);
      continue;
    }
    const [key, ...value] = arg.slice(2).split("=");
    options[key] = value.length ? value.join("=") : true;
  }
  options.priority ??= "1";
  options.tags ||= "";
  return { command, positional, options };
}

function createBoard({ prefix = "T", limit = 20 } = {}) {
  let nextId = 1;
  const tasks = new Map();
  const history = [];
  const listeners = new Set();
  const metadata = new WeakMap();
  const identity = Symbol("board");
  const audit = [];

  function emit(kind, task) {
    const event = `${kind}:${task.id}`;
    audit.push(event);
    for (const listener of listeners) listener(event);
  }

  function add(title, { priority = 1, tags = [] } = {}) {
    if (!title?.trim()) throw new TypeError("empty title");
    if (tasks.size >= limit) throw new RangeError("board full");
    const task = {
      id: `${prefix}${nextId++}`, title: title.trim(), priority: +priority,
      tags: [...new Set(tags)], done: false, [identity]: true,
    };
    tasks.set(task.id, task);
    metadata.set(task, { revision: 0 });
    history.push(() => { tasks.delete(task.id); emit("undo", task); });
    emit("add", task);
    return task.id;
  }

  function update(id, changes) {
    const task = tasks.get(id);
    if (!task) throw new RangeError(`missing:${id}`);
    const before = { ...task };
    Object.assign(task, changes);
    metadata.get(task).revision++;
    history.push(() => { Object.assign(task, before); emit("restore", task); });
    emit("update", task);
    return task;
  }

  function transaction(action) {
    const checkpoint = history.length;
    try {
      const result = action();
      audit.push("commit");
      return result;
    } catch (error) {
      while (history.length > checkpoint) history.pop()();
      audit.push(`rollback:${error.message}`);
      throw error;
    } finally {
      audit.push("settled");
    }
  }

  function list(predicate = () => true) {
    return [...tasks.values()].filter(predicate).map(task => {
      const { [identity]: hidden, ...publicTask } = task;
      return { ...publicTask, revision: metadata.get(task).revision };
    });
  }

  function watch(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  return {
    add, update, transaction, list, watch, audit,
    get size() { return tasks.size; },
    undo() { return history.pop()?.() ?? null; },
  };
}

function execute(board, line) {
  const { command, positional: [first, ...rest], options } = parseCommand(line);
  switch (command) {
    case "add":
      return board.add(first, {
        priority: options.priority,
        tags: options.tags ? options.tags.split(",") : [],
      });
    case "done":
    case "finish":
      return board.update(first, { done: true }).id;
    case "rename":
      return board.update(first, { title: rest.join(" ") }).title;
    case "undo":
      return board.undo();
    case "list":
      return board.list(task => !options.open || !task.done);
    default:
      throw new SyntaxError(`unknown command:${command}`);
  }
}

function runCommands(lines) {
  const board = createBoard();
  const output = [];
  for (const line of lines) {
    try {
      output.push({ line, value: execute(board, line) });
    } catch (error) {
      output.push({ line, error: `${error.name}:${error.message}` });
    }
  }
  return { output, tasks: board.list(), audit: board.audit };
}

function transactionScenario() {
  const board = createBoard({ limit: 2 });
  const notices = [];
  const stop = board.watch(event => notices.push(event));
  board.add("keep");
  let failure;
  try {
    board.transaction(() => {
      board.update("T1", { title: "temporary" });
      board.add("remove");
      board.add("overflow");
    });
  } catch ({ name, message }) {
    failure = `${name}:${message}`;
  }
  stop();
  board.transaction(() => board.update("T1", { done: true }));
  return { failure, tasks: board.list(), notices, audit: board.audit, size: board.size };
}

function selectionScenario() {
  const rows = [["parser", 3], ["printer", 0], ["scope", 2]];
  const deferred = [];
  const selected = [];
  outer: for (let row = 0; row < rows.length; row++) {
    const [name, priority = 1] = rows[row];
    for (let slot = 0; slot < 3; slot++) {
      if (!priority) continue outer;
      if (slot === priority) break;
      deferred.push(() => `${row}:${slot}:${name}`);
      if (selected.length === 4) break outer;
      selected.push({ name, slot });
    }
  }
  return { selected, deferred: deferred.map(fn => fn()) };
}

function pluginScenario() {
  const events = [];
  const token = Symbol("plugin");
  const raw = {
    title: "lint", [token]: 7,
    get score() { events.push("get:score"); return 3; },
  };
  Object.defineProperty(raw, "secret", { value: 9, enumerable: false });
  const plugin = new Proxy(raw, {
    ownKeys(target) { events.push("keys"); return Reflect.ownKeys(target); },
    getOwnPropertyDescriptor(target, key) {
      events.push(`descriptor:${String(key)}`);
      return Reflect.getOwnPropertyDescriptor(target, key);
    },
    get(target, key, receiver) {
      events.push(`get:${String(key)}`);
      return Reflect.get(target, key, receiver);
    },
  });
  const { title, ...settings } = plugin;
  let evaluations = 0;
  const key = { [Symbol.toPrimitive](hint) { events.push(hint); return "score"; } };
  settings[key] ??= ++evaluations;
  settings.enabled ||= true;
  settings.enabled &&= "yes";
  const absent = null;
  const skipped = absent?.[events.push("unexpected")]?.(++evaluations);
  return {
    title, score: settings.score, token: settings[token], enabled: settings.enabled,
    secret: Object.hasOwn(settings, "secret"), evaluations, skipped, events,
  };
}

function iteratorScenario() {
  const events = [];
  const jobs = {
    [Symbol.iterator]() {
      let next = 0;
      return {
        next() { events.push(`next:${next}`); return { value: ++next, done: next > 4 }; },
        return() { events.push("close"); return { done: true }; },
      };
    },
  };
  const accepted = [];
  try {
    for (const id of jobs) {
      if (id === 2) continue;
      accepted.push(id);
      if (id === 3) break;
    }
    for (const id of jobs) {
      events.push(`fail:${id}`);
      throw new Error("cancel");
    }
  } catch (error) {
    events.push(error.message);
  } finally {
    events.push("finally");
  }
  return { accepted, events };
}

function classScenario() {
  const events = [];
  class Reporter {
    constructor(prefix = "task") { this.prefix = prefix; }
    format({ id, title }) { return `${this.prefix}:${id}:${title}`; }
    get label() { return this.prefix.toUpperCase(); }
    set label(value) { this.prefix = value.toLowerCase(); }
    static kind() { return "text"; }
  }
  const reporter = new Reporter("build");
  reporter.label = "CHECK";
  const method = reporter.format;
  try { method({ id: "T0", title: "unbound" }); } catch (error) { events.push(error.name); }
  return {
    text: reporter.format({ id: "T1", title: "parser" }),
    label: reporter.label, kind: Reporter.kind(), events,
  };
}

function advancedClassScenario() {
  const events = [];
  const formatKey = Symbol("format");
  class Base {
    constructor(prefix) { this.prefix = prefix; }
    render(value) { return `${this.prefix}:${value}`; }
    static get kind() { return "report"; }
  }
  class Metered extends Base {
    #calls = 0;
    suffix = "!";
    static instances = 0;
    static { events.push(`init:${super.kind}`); }
    constructor(...args) { super(...args); Metered.instances++; }
    [formatKey](value) { this.#calls++; return super.render(value) + this.suffix; }
    get calls() { return this.#calls; }
    hasCounter(other) { return #calls in other; }
    makeFormatter() { return value => this[formatKey](value); }
  }
  const reporter = new Metered("batch");
  const render = reporter.makeFormatter();
  return {
    text: render(3), calls: reporter.calls, instances: Metered.instances,
    own: reporter.hasCounter(reporter), foreign: reporter.hasCounter({}), events,
  };
}

function generatorScenario() {
  const events = [];
  function* jobs() {
    try {
      const prefix = yield "ready";
      yield* [prefix, "finish"];
      return "complete";
    } catch (error) {
      events.push(error.message);
      yield "retry";
    } finally {
      events.push("release");
    }
  }
  const first = jobs();
  const steps = [first.next(), first.next("work"), first.return("cancel")];
  const second = jobs();
  steps.push(second.next(), second.throw(new Error("abort")), second.next());
  return { steps, events };
}

async function asyncScenario() {
  const events = [];
  async function save(id, reject = false) {
    events.push(`start:${id}`);
    try {
      await Promise.resolve();
      if (reject) throw new Error(`offline:${id}`);
      events.push(`saved:${id}`);
      return id * 2;
    } finally {
      events.push(`settled:${id}`);
    }
  }
  const results = await Promise.allSettled([save(1), save(2, true)]);
  async function* stream() {
    try { yield await save(3); yield 99; }
    finally { events.push("stream:closed"); }
  }
  const streamed = [];
  for await (const value of stream()) {
    streamed.push(value);
    break;
  }
  return {
    results: results.map(({ status, value, reason }) => ({ status, value, error: reason?.message })),
    streamed, events,
  };
}

function codecScenario() {
  const events = [];
  function format(parts, ...values) {
    events.push(parts.raw[0]);
    return parts.reduce((text, part, index) => text + part + (values[index] ?? ""), "");
  }
  const quota = 9_007_199_254_740_993n;
  const bytes = new Uint8Array([1, 255, 16]);
  const view = new DataView(bytes.buffer);
  const [, high, ...tail] = bytes;
  const sparse = [, undefined, -0, NaN, Infinity];
  const total = quota + BigInt(view.getUint16(0));
  return {
    text: format`quota=${total}; high=${high}`, total, tail,
    hole: 0 in sparse, explicit: 1 in sparse, negative_zero: sparse[2],
    nan: sparse[3], infinity: sparse[4], events,
  };
}

function taskboard(scenario, lines = []) {
  switch (scenario) {
    case "parser": return parseCommand('add "ship parser" --priority=3 --tags=v8,js --owner=a=b');
    case "commands": return runCommands(lines);
    case "workflow": return runCommands([
      'add "ship parser" --priority=3 --tags=v8,js,v8',
      "add 'audit scopes'", "finish T1", 'rename T2 "audit closures"',
      "list --open", "undo", "done missing", "unknown",
    ]);
    case "transactions": return transactionScenario();
    case "selection": return selectionScenario();
    case "plugins": return pluginScenario();
    case "iterators": return iteratorScenario();
    case "classes": return classScenario();
    case "advanced_classes": return advancedClassScenario();
    case "generators": return generatorScenario();
    case "async": return asyncScenario();
    case "codec": return codecScenario();
    default: throw new RangeError(`unknown scenario:${scenario}`);
  }
}

globalThis.taskboard = taskboard;
