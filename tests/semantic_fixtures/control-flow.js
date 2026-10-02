function branchFlow(value, events) {
  function check(label, result) {
    events[events.length] = label;
    return result;
  }
  if (value < 0) return "negative";
  if (check("first", value > 1) && (check("second", value < 4) || check("third", value === 5))) {
    if (value === 2) return "two";
    events[events.length] = "branch-accepted";
  } else {
    events[events.length] = "branch-rejected";
  }
  return value ? "nonzero" : "zero";
}

function logicalFlow(mask) {
  const events = [];
  function pick(label, bit) {
    events[events.length] = label;
    return mask & bit;
  }
  let value;
  if ((pick("left-a", 1) || pick("left-b", 2)) && (pick("right-c", 4) || pick("right-d", 8))) {
    value = "both-sides";
  } else {
    value = "missing-side";
  }
  if (pick("outer-if", 1)) {
    if (pick("inner-if", 2)) events[events.length] = "inner-hit";
  } else {
    events[events.length] = "outer-fallback";
  }
  const fallback = (pick("pair-a", 1) && pick("pair-b", 2)) || (pick("pair-c", 4) && pick("pair-d", 8));
  const choice = pick("choose-a", 1)
    ? (pick("choose-b", 2) ? "choice-left" : "choice-middle")
    : (pick("choose-c", 4) ? "choice-right" : "choice-none");
  events[events.length] = "joined-once";
  return { value, fallback, choice, events };
}

function conditionLoop(limit) {
  const events = [];
  let index = 0;
  function check(value) {
    events[events.length] = value;
    return value;
  }
  while (check(index < 2) || check(index < limit)) {
    index++;
    if (index === 4) break;
  }
  return { index, events };
}

function assignmentFlow(flag) {
  const events = [];
  function record(value) {
    events[events.length] = value;
    return value;
  }
  let left = 10;
  let right = 20;
  const chosen = flag ? (left = record(7)) : (right = record(9));
  const andResult = flag && (left = record(11));
  const orResult = flag || (right = record(13));
  return { chosen, andResult, orResult, left, right, events };
}

function fallbackFlow(input) {
  let left = 10;
  let right = 20;
  const nullish = input ?? (left = 7);
  const falsy = input || (right = 9);
  return { nullish, falsy, left, right };
}

function logicalAssignmentFlow(input) {
  let defaulted = input;
  const nullish = (defaulted ??= 7);
  let fallback = input;
  const falsy = (fallback ||= 9);
  let guarded = input;
  const truthy = (guarded &&= 11);
  return { nullish, defaulted, falsy, fallback, truthy, guarded, resultType: typeof truthy };
}

function whileFlow(values) {
  const events = [];
  let index = 0;
  let total = 0;
  while (index < values.length) {
    const value = values[index++];
    if (value < 0) continue;
    if (value > 10) break;
    total += value;
    events[events.length] = value;
  }
  return { index, total, events };
}

function forFlow(limit) {
  const events = [];
  let total = 0;
  for (let index = 0; index < limit; events[events.length] = "loop-step", index++) {
    if (index % 2 === 0) continue;
    if (index > 5) break;
    total += index;
    events[events.length] = index;
  }
  return { total, events };
}

function doWhileFlow(limit) {
  const events = [];
  let index = 0;
  function again() {
    events[events.length] = "loop-test";
    return index < limit;
  }
  do {
    index++;
    if (index % 2 === 0) continue;
    if (index > 4) break;
    events[events.length] = index;
  } while (again());
  return { index, events };
}

function nestedFlow(limit) {
  const events = [];
  for (let outer = 0; outer < limit; outer++) {
    for (let inner = 0; inner < 4; inner++) {
      if (inner === 1) continue;
      if (outer === 2) return events;
      if (inner === 3) break;
      events[events.length] = outer * 10 + inner;
    }
    events[events.length] = "outer-next";
  }
  return events;
}

const branchEvents = [];
const combinations = [];
for (let mask = 0; mask < 16; mask++) combinations[mask] = logicalFlow(mask);
globalThis.__semantic_result = {
  branches: [branchFlow(-1, branchEvents), branchFlow(0, branchEvents), branchFlow(1, branchEvents),
    branchFlow(2, branchEvents), branchFlow(3, branchEvents), branchFlow(4, branchEvents),
    branchFlow(5, branchEvents)],
  branchEvents,
  combinations,
  assignmentTrue: assignmentFlow(true),
  assignmentFalse: assignmentFlow(false),
  fallbackZero: fallbackFlow(0),
  fallbackFalse: fallbackFlow(false),
  fallbackNull: fallbackFlow(null),
  fallbackUndefined: fallbackFlow(undefined),
  fallbackValue: fallbackFlow(2),
  logicalZero: logicalAssignmentFlow(0),
  logicalFalse: logicalAssignmentFlow(false),
  logicalNull: logicalAssignmentFlow(null),
  logicalUndefined: logicalAssignmentFlow(undefined),
  logicalValue: logicalAssignmentFlow(2),
  conditionExhausted: conditionLoop(0),
  conditionBreak: conditionLoop(6),
  whileEmpty: whileFlow([]),
  whileExhausted: whileFlow([-1, 2, -3, 4]),
  whileBreak: whileFlow([-1, 2, 11, 4]),
  forEmpty: forFlow(0),
  forExhausted: forFlow(5),
  forBreak: forFlow(10),
  doOnce: doWhileFlow(0),
  doContinue: doWhileFlow(2),
  doBreak: doWhileFlow(10),
  nestedEmpty: nestedFlow(0),
  nestedExhausted: nestedFlow(2),
  nestedReturn: nestedFlow(4),
};
