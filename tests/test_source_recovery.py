from __future__ import annotations

import unittest

from decompiler.recovery.destructuring import recover_object_rest
from decompiler.recovery.expressions import compact_accumulator_expressions
from decompiler.recovery.literals import recover_object_literals
from decompiler.recovery.propagation import simplify_lines
from decompiler.runtime import runtime_prelude
from tests.test_semantic_equivalence import observe_javascript


class SourceRecoveryTests(unittest.TestCase):
    def assert_equivalent(self, original, recovered, setup="", nested=(), remaining=()):
        def program(lines, functions):
            return "\n".join([
                runtime_prelude(), setup, "function run() {",
                "let ACCU, r0, r1, r2, r3, r4, r5;", *functions, *lines, "}",
                "globalThis.__semantic_result = run();",
            ])
        self.assertEqual(
            observe_javascript(program(original, nested)),
            observe_javascript(program(recovered, remaining)),
            "\n".join(recovered),
        )

    def test_literal_builders_preserve_effects_and_escaping_references(self):
        setup = '''
const events = [];
function mark(value) { events.push(value); return value; }
const key = { toString() { events.push("key"); return "value"; } };
Object.defineProperty(Object.prototype, "value", {
  set(value) { events.push("prototype"); }, configurable: true
});
let escaped;
function publish(value) { escaped = value; }
'''
        cases = [
            [
                "r0 = {}", "r1 = ToName(key)",
                'define_literal_property(r0, r1, mark(7), false, true)',
                "return { value: r0.value, events }",
            ],
            [
                "r0 = { value: undefined, later: mark(3) }",
                'define_literal_property(r0, "value", mark(7), false, true)',
                "return { value: r0.value, events }",
            ],
            [
                "r0 = {}", "publish(r0)",
                'define_literal_property(r0, "value", mark(7), false, true)',
                "return { value: escaped.value, events }",
            ],
            [
                "r0 = {}", "r0.value = mark(7)",
                "return { value: r0.value, events }",
            ],
            [
                "r0 = {}", "r1 = ToName(key)",
                'define_literal_property(r0, r1, 7, false, true)',
                "return { value: r0.value, key: r1, events }",
            ],
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                recovered, _ = recover_object_literals(lines, [], {})
                self.assert_equivalent(lines, recovered, setup)

    def test_ordinary_functions_keep_name_identity_and_constructability(self):
        nested = ["function ordinary() {\n  return 7\n}"]
        lines = [
            "r0 = { ordinary }",
            'return [r0.ordinary.name, "prototype" in r0.ordinary, r0.ordinary === ordinary]',
        ]
        for kind in (None, "NormalFunction", "ConciseMethod"):
            # The second reference forbids duplicating a function even if its kind is known.
            with self.subTest(kind=kind):
                recovered, remaining = recover_object_literals(lines, nested, {"ordinary": kind})
                self.assert_equivalent(lines, recovered, nested=nested, remaining=remaining)
        single_use = ["r0 = { ordinary }", 'return [r0.ordinary.name, "prototype" in r0.ordinary]']
        recovered, remaining = recover_object_literals(single_use, nested, {"ordinary": "NormalFunction"})
        self.assert_equivalent(single_use, recovered, nested=nested, remaining=remaining)

    def test_rest_checks_null_before_key_conversion_and_reads_once(self):
        lines = [
            "ACCU = arg0", "r0 = arg0", "if (!(isNullish(ACCU))) {", "}", "else {",
            "  ACCU = ThrowPatternAssignmentNonCoercible(r0)", "}",
            "ACCU = ToName(arg1)", "r1 = ACCU", "r2 = r0[ACCU]",
            "r3 = CopyDataPropertiesWithExcludedPropertiesOnStack(r0, r1)",
            "return { selected: r2, rest: r3, events }",
        ]
        recovered = recover_object_rest(lines)
        self.assertIn("...r3 } = arg0", "\n".join(recovered))
        setup = '''
const events = [];
const arg1 = { toString() { events.push("key"); return "selected"; } };
'''
        for source in ("null", "{ get selected() { events.push('get'); return 7; }, other: 9 }"):
            with self.subTest(source=source):
                def wrap(body):
                    return ["try {", *body, "} catch (error) { return { name: error.name, events }; }"]
                self.assert_equivalent(wrap(lines), wrap(recovered), setup + f"const arg0 = {source};")
        live_key = lines[:-1] + ["return [r1, r2, r3]"]
        self.assertEqual(recover_object_rest(live_key), live_key)

    def test_accumulator_cleanup_preserves_getters_and_branch_values(self):
        setup = '''const events = [];
const source = {
  get value() { events.push("get"); return 7; },
  get other() { events.push("other"); return 11; }
};'''
        cases = [
            ["ACCU = source.value", "return events"],
            ["ACCU = source.value", "r0 = ACCU", "return [ACCU, r0, events]"],
            ["ACCU = source.value", "if (true) {", "  r0 = ACCU", "}", "return [r0, events]"],
            ['ACCU = "ACCU"', "r0 = ACCU", "return r0"],
            ["r0 = {}", "ACCU = source.value", "r0.saved = ACCU", "return [ACCU, r0.saved, events]"],
            ["ACCU = 2", "ACCU += 3", "r0 = ACCU", "return [ACCU, r0]"],
            ["ACCU = 2", "ACCU = ++ACCU", "return ACCU"],
            ["ACCU = 2", "r0 = { ACCU: ACCU }", "return r0"],
            ['ACCU = 2', 'r0 = { "ACCU": ACCU }', 'return r0'],
            ["ACCU = [1, 2]", "ACCU = [...ACCU]", "return ACCU"],
            ["ACCU = { value: 3 }", "return { ...ACCU }"],
            ['ACCU = "ACCU"', 'return { ACCU: 3 }.ACCU'],
            ["r0 = 1", "ACCU = 0", "ACCU = (r0 === ACCU)",
             "if (truthy(ACCU)) {", "  ACCU = 7", "}", "return ACCU"],
            ["ACCU = true", "r0 = 0", "if (truthy(ACCU)) {", "  return 7", "}", "return 9"],
            ["r0 = [false, true]", "ACCU = r0.shift()", "r1 = r0.shift()",
             "if (!(truthy(ACCU))) {", "  return [ACCU, r1, r0.length]", "}", "return 9"],
            ["ACCU = undefined", "if (!(isNullish(ACCU))) {", "}", "else {",
             "  ACCU = 7", "}", "r0 = ACCU", "return [r0, ACCU]"],
            ["if (true) {", "  r0 = 7", "}", "else {", "  r0 = 9", "}", "return r0"],
            ["ACCU = 2", "if (true) {", "  ACCU = null", "  if (truthy(ACCU)) {",
             "    ACCU = 7", "  }", "}", "return ACCU"],
            ["ACCU = source.value", "if (ACCU === 7) {", "  return [ACCU, events]", "}",
             "return events"],
            ["ACCU = source.value", "if (!(ACCU !== undefined)) {", "  ACCU = 9", "}",
             "r0 = ACCU", "return [ACCU, r0, events]"],
            ["ACCU = source.value", "r1 = source.other", "if (!(ACCU !== undefined)) {",
             "  ACCU = 9", "}", "r0 = ACCU", "return [ACCU, r0, r1, events]"],
            ["ACCU = source.value", "if (!(ACCU !== undefined)) {", "  ACCU = 9", "}",
             "else {", "  ACCU = source.other", "}", "r0 = ACCU", "return [ACCU, r0, events]"],
            ["ACCU = source.value", "if (ACCU !== 7) {", "  return events", "}",
             "else {", "  return [ACCU, events]", "}"],
            ["ACCU = source.value", "if (ACCU === 7) {", '  return { ACCU, label: "ACCU", events }',
             "}", "return events"],
            ["r0 = 7", 'ACCU = "r0"', "return ACCU"],
            ['r0 = "prefix"', 'r1 = "r0 r1"', "return [r0, r1]"],
            ["r0 = 7", "r1 = { r0: r0 }", 'return [r1.r0, "r0"]'],
            ["r0 = 7", "r1 = { r0 }", "return r1"],
            ["r0 = 7", "r1 = { r0: 11 }", "ACCU = r1.r0", "return [r0, ACCU]"],
            ["ACCU = source.value", "r0 = ACCU", 'ACCU = "ACCU"', "return [r0, ACCU]"],
            ["ACCU = source.value", "r0 = ACCU", 'return [r0, "ACCU"]'],
            ["ACCU = source.value", "r0 = ACCU", "ACCU = ToName(ACCU)", "return [r0, ACCU]"],
            ["ACCU = source.value", "r0 = ACCU", "return { ACCU, saved: r0 }"],
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                self.assert_equivalent(lines, compact_accumulator_expressions(lines), setup)
                self.assert_equivalent(lines, simplify_lines(lines, recover_structures=True), setup)

    def test_property_updates_preserve_reference_evaluation(self):
        setup = '''
const events = [];
const items = [{ amount: 1 }, { amount: 2 }];
let reads = 0;
const source = {
  get child() { events.push("child"); return items[reads++ % 2]; }
};
let holder = items[0];
function swap() { events.push("swap"); holder = items[1]; return 3; }
let index = 0;
function nextKey() { events.push("key"); return index++; }
function report() { return [items, reads, index, events]; }
'''
        cases = [
            ["source.child.amount = (source.child.amount + 3)"],
            ["r0 = (source.child.amount + 3)", "source.child.amount = r0"],
            ["r0 = source.child.amount", "source.child.amount = (r0 + 3)"],
            ["ACCU = (source.child.amount + 3)", "source.child.amount = ACCU"],
            ["ACCU = source.child.amount", "ACCU = (ACCU + 3)", "source.child.amount = ACCU"],
            ["r0 = (holder.amount + swap())", "holder.amount = r0"],
            ["ACCU = (holder.amount + swap())", "holder.amount = ACCU"],
            ["items[nextKey()] = (items[nextKey()] + 3)"],
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                lines = [*lines, "return report()"]
                self.assert_equivalent(lines, simplify_lines(lines, recover_structures=True), setup)


if __name__ == "__main__":
    unittest.main()
