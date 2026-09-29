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
        setup = 'const events = []; const source = { get value() { events.push("get"); return 7; } };'
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
        ]
        for lines in cases:
            with self.subTest(lines=lines):
                self.assert_equivalent(lines, compact_accumulator_expressions(lines), setup)
                self.assert_equivalent(lines, simplify_lines(lines, recover_structures=True), setup)


if __name__ == "__main__":
    unittest.main()
