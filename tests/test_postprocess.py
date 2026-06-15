from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECOMPILER = ROOT / "decompiler"
if str(DECOMPILER) not in sys.path:
    sys.path.insert(0, str(DECOMPILER))

from postprocess import _compact_compound_assignments, simplify_lines
from parser import parse_objects


class SimplifyLinesTests(unittest.TestCase):
    def test_parser_ignores_best_effort_diagnostics_between_objects(self) -> None:
        objects = parse_objects(
            [
                "0x1001: [String] in ReadOnlySpace: #ok",
                "",
                "!0x2001: segmentfault while discovering object, skipped",
                "0x3001: [String]: #done",
            ]
        )

        self.assertEqual(len(objects), 2)
        self.assertEqual(objects[0].value, "ok")
        self.assertEqual(objects[1].value, "done")

    def test_does_not_inline_accu_as_register_value(self) -> None:
        lines = [
            "ACCU = r4",
            "ACCU = String(ACCU)",
            "r13 = ACCU",
            'ACCU = ":"',
            "ACCU = (r13 + ACCU)",
            "r13 = ACCU",
        ]

        simplified = simplify_lines(lines)

        self.assertIn("ACCU = (r13 + ACCU)", simplified)
        self.assertNotIn("ACCU = (ACCU + ACCU)", simplified)

    def test_preserves_accu_load_used_by_next_accu_assignment(self) -> None:
        lines = [
            "ACCU = -1",
            "ACCU = (r6 == ACCU)",
            "if (ACCU) goto offset_379",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, lines)

    def test_preserves_string_accu_load_used_by_next_accu_assignment(self) -> None:
        lines = [
            'ACCU = "zh-Hans"',
            "ACCU = (context_slot[36] === ACCU)",
            "if (ACCU) goto offset_657",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, lines)

    def test_recovers_constant_dispatch_assignment_map(self) -> None:
        lines = [
            "r0 = context_slot[36]",
            'ACCU = "zh-CN"',
            "ACCU = (context_slot[36] === ACCU)",
            "if (ACCU) goto offset_657",
            'ACCU = "zh-Hans"',
            "ACCU = (r0 === ACCU)",
            "if (ACCU) goto offset_657",
            'ACCU = "zh-TW"',
            "ACCU = (r0 === ACCU)",
            "if (ACCU) goto offset_663",
            "// goto offset_873",
            'script_context[36] = "zh-Hans"',
            "// goto offset_877",
            'script_context[36] = "zh-Hant"',
            "// goto offset_877",
            'script_context[36] = "Base"',
            "return context_slot[36]",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r0 = context_slot[36]",
                'script_context[36] = ({"zh-CN": "zh-Hans", "zh-Hans": "zh-Hans", "zh-TW": "zh-Hant"}[r0] ?? "Base")',
                "return context_slot[36]",
            ],
        )

    def test_drops_redundant_empty_else_truthy_guard(self) -> None:
        lines = [
            "if (!truthy(arg0.hasUnsaved)) {",
            "}",
            "else {",
            "  ACCU = arg0.hasUnsaved",
            "  if (!truthy(ACCU)) goto offset_288",
            "}",
            "try {",
            '  console.record("recoverWindow")',
            "} catch (e) {",
            "  throw e",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "try {",
                '  console.record("recoverWindow")',
                "} catch (e) {",
                "  throw e",
                "}",
            ],
        )

    def test_preserves_unused_context_slot_call_without_accu(self) -> None:
        lines = [
            "ACCU = context_slot[7]",
            "r0 = ACCU",
            "ACCU = r0()",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "context_slot[7]()",
            ],
        )

    def test_compacts_string_concat_chain(self) -> None:
        lines = [
            "ACCU = r4",
            "ACCU = String(ACCU)",
            "r13 = ACCU",
            'ACCU = ":"',
            "ACCU = (r13 + ACCU)",
            "r13 = ACCU",
            "ACCU = r3",
            "ACCU = String(ACCU)",
            "return (r13 + ACCU)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r13 = String(r4)",
                'r13 += ":"',
                "return (r13 + String(r3))",
            ],
        )

    def test_compacts_concat_accu_return(self) -> None:
        lines = [
            "ACCU = r7",
            "ACCU = String(ACCU)",
            "ACCU = (r13 + ACCU)",
            "return ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return (r13 + String(r7))"])

    def test_normalizes_nested_block_indentation(self) -> None:
        lines = [
            "  if (outer) {",
            "  if (inner) {",
            "  return true",
            "  }",
            "  }",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "  if (outer) {",
                "    if (inner) {",
                "      return true",
                "    }",
                "  }",
            ],
        )

    def test_recovers_accu_conditional_expr_before_concat(self) -> None:
        lines = [
            "ACCU = r8.ok",
            "ACCU = false",
            "ACCU = (r8.ok === ACCU)",
            "if (truthy(ACCU)) {",
            '  ACCU = "bad"',
            "}",
            "else {",
            '  ACCU = "ok"',
            "}",
            "ACCU = String(ACCU)",
            "ACCU = (r13 + ACCU)",
            "r13 = ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            ['r13 += String(((r8.ok === false) ? "bad" : "ok"))'],
        )

    def test_drops_duplicate_call_before_assignment(self) -> None:
        lines = [
            "r13.call(r14)",
            "r3 = r13.call(r14)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r3 = r13.call(r14)"])

    def test_drops_duplicate_pure_accu_load_before_same_register_value(self) -> None:
        lines = [
            "ACCU = 0",
            "r4 = 0",
            "for (const item of r8) {",
            "  r4 += item",
            "}",
            "return r4",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r4 = 0",
                "for (const item of r8) {",
                "  r4 += item",
                "}",
                "return r4",
            ],
        )

    def test_keeps_duplicate_accu_load_when_later_condition_reads_accu(self) -> None:
        lines = [
            "ACCU = arg0",
            "r0 = arg0",
            "if (!(isNullish(ACCU))) {",
            "  return r0.value",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertIn("ACCU = arg0", simplified)

    def test_inlines_accu_equality_condition_load(self) -> None:
        lines = [
            'ACCU = closure["brand"]',
            "if (!(ACCU === undefined)) {",
            "  r1 = ACCU",
            "  r1.call(this)",
            "}",
            "return undefined",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                'if (!(closure["brand"] === undefined)) {',
                '  closure["brand"].call(this)',
                "}",
                "return undefined",
            ],
        )

    def test_rewrites_bound_method_call_from_register(self) -> None:
        lines = [
            "r13 = r14.toUpperCase",
            "r13.call(r14)",
            "r3 = r13.call(r14)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r3 = r14.toUpperCase()",
            ],
        )

    def test_rewrites_direct_bound_method_call(self) -> None:
        lines = ["return JSON.parse.call(JSON, arg0)"]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return JSON.parse(arg0)"])

    def test_rewrites_bound_method_call_with_nested_arguments(self) -> None:
        lines = ['return obj.method.call(obj, pair(1, 2), "a,b", [3, 4])']

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ['return obj.method(pair(1, 2), "a,b", [3, 4])'])

    def test_rewrites_bound_method_call_inside_string_wrapper(self) -> None:
        lines = [
            "r2 = r3.toUpperCase",
            "r1 = String(r2.call(r3))",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            ["r1 = String(r3.toUpperCase())"],
        )

    def test_rewrites_bound_method_call_inside_compound_assignment(self) -> None:
        lines = [
            "r4 = Math.max",
            "r3 += r4.call(Math, ...r0)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            ["r3 += Math.max(...r0)"],
        )

    def test_rewrites_bound_method_call_inside_binary_return(self) -> None:
        lines = [
            "r4 = r1.sum",
            "return (r3 + r4.call(r1))",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return (r3 + r1.sum())"])

    def test_rewrites_direct_member_call_inside_binary_return(self) -> None:
        lines = ['return (r3 + r2.join.call(r2, ","))']

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ['return (r3 + r2.join(","))'])

    def test_keeps_call_with_different_receiver_inside_binary_return(self) -> None:
        lines = ["return (r3 + Array.prototype.slice.call(arguments, 1))"]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return (r3 + Array.prototype.slice.call(arguments, 1))"])

    def test_rewrites_identifier_call_with_undefined_receiver(self) -> None:
        lines = ['r3 = collect.call(undefined, "x", ...r0)']

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ['r3 = collect("x", ...r0)'])

    def test_compacts_compound_assignment_with_saved_old_value(self) -> None:
        lines = [
            "ACCU = item",
            "ACCU = (r0 + ACCU)",
            "r27 = r0",
            "r0 = ACCU",
        ]

        simplified = _compact_compound_assignments(lines)

        self.assertEqual(simplified, ["r0 += item"])

    def test_collapses_accu_store_return(self) -> None:
        lines = [
            "ACCU = calc(1, 2, 3)",
            "r0 = calc(1, 2, 3)",
            "return ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return calc(1, 2, 3)"])

    def test_simplifies_accu_throw(self) -> None:
        lines = [
            "if (!(r5 === 0)) {",
            "  ACCU = r4",
            "  throw ACCU",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "if (!(r5 === 0)) {",
                "  throw r4",
                "}",
            ],
        )

    def test_names_async_reject_handler_exception(self) -> None:
        lines = [
            "return _AsyncFunctionResolve(r0, r5)",
            "r5 = ACCU",
            "// SetPendingMessage",
            "r4 = r0",
            "return _AsyncFunctionReject(r0, r5)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "return _AsyncFunctionResolve(r0, r5)",
                "r5 = async_reject_exception",
                "// SetPendingMessage",
                "return _AsyncFunctionReject(r0, r5)",
            ],
        )

    def test_collapses_accu_store_when_accu_is_not_used_later(self) -> None:
        lines = [
            "ACCU = arg0?.profile?.name",
            "r0 = ACCU",
            "return r0",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r0 = arg0?.profile?.name", "return r0"])

    def test_collapses_context_creation_before_push_context(self) -> None:
        lines = [
            "ACCU = create_function_context(ScopeInfo_FUNCTION_SCOPE, 1)",
            "r0 = pushContext(ACCU)",
            "script_context[2] = arg0",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r0 = pushContext(create_function_context(ScopeInfo_FUNCTION_SCOPE, 1))",
                "script_context[2] = arg0",
            ],
        )

    def test_compacts_stringified_return_with_literal_prefix(self) -> None:
        lines = [
            "ACCU = r0.toUpperCase()",
            "ACCU = String(ACCU)",
            'return ("hi," + ACCU)',
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ['return ("hi," + String(r0.toUpperCase()))'])

    def test_compacts_stringified_accu_binary_return(self) -> None:
        lines = [
            "ACCU = Number(r3)",
            "return (r1 + String((ACCU + 1)))",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return (r1 + String((Number(r3) + 1)))"])

    def test_drops_unused_pure_register_assignment(self) -> None:
        lines = [
            "r2 = arg0.exec",
            "r1 = r2",
            "r2 = Number",
            "return Number(arg0)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return Number(arg0)"])

    def test_drops_overwritten_unused_member_register_assignment(self) -> None:
        lines = [
            "r2 = r3.toUpperCase",
            "r1 = String(r3.toUpperCase())",
            "r2 = r0[2]",
            "return r2",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r1 = String(r3.toUpperCase())",
                "return r0[2]",
            ],
        )

    def test_keeps_live_member_register_assignment(self) -> None:
        lines = [
            "r2 = r3.toUpperCase",
            "return r2",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return r3.toUpperCase"])

    def test_drops_unused_literal_and_alias_register_assignments(self) -> None:
        lines = [
            "r4 = collect",
            "r5 = null",
            'r6 = "v"',
            "r7 = r0",
            'r2 = collect.call(null, "v", ...r0)',
            "return r2",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ['r2 = collect.call(null, "v", ...r0)', "return r2"])

    def test_keeps_unused_effectful_register_assignment(self) -> None:
        lines = [
            "r2 = fn()",
            "return 1",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r2 = fn()", "return 1"])

    def test_compacts_accu_binary_store(self) -> None:
        lines = [
            "ACCU = arg1",
            "ACCU = (arg0 + ACCU)",
            "r0 = ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r0 = (arg0 + arg1)"])

    def test_compacts_accu_left_binary_return(self) -> None:
        lines = [
            "ACCU = arg0",
            "return (ACCU - 10)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return (arg0 - 10)"])

    def test_compacts_accu_left_binary_store(self) -> None:
        lines = [
            "ACCU = arg0",
            "ACCU = (ACCU + 1)",
            "r0 = ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r0 = (arg0 + 1)"])

    def test_compacts_negated_accu_compare_if_with_immediate_rhs(self) -> None:
        lines = [
            "r5 = _GeneratorGetResumeMode(r0)",
            "ACCU = 0",
            "ACCU = (r5 === ACCU)",
            "if (!(truthy(ACCU))) {",
            "  ACCU = r4",
            "  throw ACCU",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r5 = _GeneratorGetResumeMode(r0)",
                "if (!(r5 === 0)) {",
                "  throw r4",
                "}",
            ],
        )

    def test_compacts_saved_receiver_binary_property_store(self) -> None:
        lines = [
            "ACCU = this.n",
            "r2 = this.n",
            "ACCU = r0",
            "ACCU = (r2 + ACCU)",
            "this.n = ACCU",
            "ACCU = this.n",
            "return ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["this.n = (this.n + r0)", "return this.n"])

    def test_compacts_adjacent_binary_temp_register(self) -> None:
        lines = [
            "r4 = r1.value",
            "r5 = (r4 + r2.value)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r5 = (r1.value + r2.value)"])

    def test_compacts_adjacent_binary_temp_property_store(self) -> None:
        lines = [
            "r3 = this[context_slot[2]]",
            "this[context_slot[2]] = (r3 + r0)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["this[context_slot[2]] = (this[context_slot[2]] + r0)"])

    def test_compacts_accu_binary_return(self) -> None:
        lines = [
            "ACCU = arg0",
            "return (context_slot[2] + ACCU)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return (context_slot[2] + arg0)"])

    def test_does_not_inline_literal_register_into_assignment_target(self) -> None:
        lines = [
            "ACCU = []",
            "r0 = []",
            "ACCU = 0",
            "r1 = 0",
            "ACCU = arg0",
            "r0[r1] = ACCU",
        ]

        simplified = simplify_lines(lines)

        self.assertEqual(simplified[-1], "r0[0] = arg0")
        self.assertNotIn("[][0] = arg0", simplified)

    def test_array_mutation_invalidates_cached_literal_value(self) -> None:
        lines = [
            "ACCU = []",
            "r3 = []",
            "r4 = 0",
            "r3[r4] = arg0",
            "r0 = r3",
        ]

        simplified = simplify_lines(lines)

        self.assertEqual(simplified[-1], "r0 = r3")
        self.assertNotIn("r0 = []", simplified)

    def test_does_not_cache_accu_alias_without_known_value(self) -> None:
        lines = [
            "if (cond) {",
            "  ACCU = arg0",
            "}",
            "r0 = ACCU",
            "ACCU = r0",
            "return ACCU",
        ]

        simplified = simplify_lines(lines)

        self.assertIn("ACCU = r0", simplified)
        self.assertNotIn("ACCU = ACCU", simplified)

    def test_invalidates_register_alias_when_source_register_is_reassigned(self) -> None:
        lines = [
            "r2 = r4",
            "r4 = r1.value",
            "ACCU = r2.value",
            "return ACCU",
        ]

        simplified = simplify_lines(lines)

        self.assertEqual(
            simplified,
            [
                "r2 = r4",
                "r4 = r1.value",
                "ACCU = r2.value",
                "return ACCU",
            ],
        )

    def test_single_use_inline_does_not_cross_source_register_reassignment(self) -> None:
        lines = [
            "r2 = r4",
            "ACCU = r1.value",
            "r4 = r1.value",
            "ACCU = r2.value",
            "ACCU = (r4 + ACCU)",
            "r5 = ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertIn("r5 = (r1.value + r2.value)", simplified)
        self.assertNotIn("r5 = (r4 + r4.value)", simplified)

    def test_single_use_inline_does_not_replace_compound_assignment_target(self) -> None:
        lines = [
            "r9 = 2",
            "r9 += 1",
            "return r9",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r9 = 2", "r9 += 1", "return r9"])

    def test_keeps_accu_load_that_flows_out_of_block(self) -> None:
        lines = [
            "if (!(isNullish(ACCU))) {",
            "  ACCU = r2.city",
            "}",
            "else {",
            "  ACCU = undefined",
            "}",
            "return ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertIn("  ACCU = r2.city", simplified)

    def test_compacts_accu_binary_saved_old_value_return(self) -> None:
        lines = [
            "ACCU = arg2",
            "ACCU = (r0 + ACCU)",
            "r1 = r0",
            "r0 = ACCU",
            "return (ACCU * 2)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r0 += arg2", "return (r0 * 2)"])

    def test_recovers_accu_conditional_binary_return(self) -> None:
        lines = [
            "if (truthy(r3.done)) {",
            "  ACCU = r3.value",
            "}",
            "else {",
            "  ACCU = 0",
            "}",
            "return (r4 + ACCU)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return (r4 + (r3.done ? r3.value : 0))"])

    def test_compacts_self_binary_assignment(self) -> None:
        lines = ['r13 = (r13 + ":")']

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ['r13 += ":"'])

    def test_strips_for_of_state_initializers(self) -> None:
        lines = [
            "ACCU = false",
            "r6 = false",
            "ACCU = HOLE",
            "r9 = HOLE",
            "r10 = context",
            "for (const item of arg0) {",
            "  r0 += item",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "for (const item of arg0) {",
                "  r0 += item",
                "}",
            ],
        )

    def test_strips_for_of_recovery_noise_inside_loop_body(self) -> None:
        lines = [
            "for (const item of arg0) {",
            "  ACCU = item",
            "  r22 = false",
            "  for (const item1 of item) {",
            "    ACCU = item1",
            "    if (item1 > 0) {",
            "      r0 += item1",
            "    }",
            "  }",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "for (const item of arg0) {",
                "  for (const item1 of item) {",
                "    if (item1 > 0) {",
                "      r0 += item1",
                "    }",
                "  }",
                "}",
            ],
        )

    def test_keeps_for_of_accu_move_when_accu_is_used(self) -> None:
        lines = [
            "for (const item of arg0) {",
            "  ACCU = item",
            "  if (truthy(ACCU)) {",
            "    r0 += item",
            "  }",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "for (const item of arg0) {",
                "  if (truthy(item)) {",
                "    r0 += item",
                "  }",
                "}",
            ],
        )

    def test_renames_for_of_loop_var_when_source_uses_same_name(self) -> None:
        lines = [
            "for (const item of arg0) {",
            "  for (const item of item) {",
            "    if (item > 0) {",
            "      r0 += item",
            "    }",
            "  }",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "for (const item of arg0) {",
                "  for (const item1 of item) {",
                "    if (item1 > 0) {",
                "      r0 += item1",
                "    }",
                "  }",
                "}",
            ],
        )

    def test_rewrites_iterator_result_value_to_for_of_item(self) -> None:
        lines = [
            "ACCU = GetIterator(arg0)",
            "r1 = GetIterator(arg0)",
            "ACCU = r1.next",
            "r2 = r1.next",
            "ACCU = false",
            "while (!(truthy(ACCU))) {",
            "  r3 = r2.call(r1)",
            "  if (!(truthy(ACCU))) {",
            "    r4 = r3",
            "    r0[r5] = r3.value",
            "    r5 += 1",
            "  }",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "ACCU = false",
                "for (const item of arg0) {",
                "  r0[r5] = item",
                "  r5 += 1",
                "}",
            ],
        )

    def test_compacts_object_values_spread_array_builder(self) -> None:
        lines = [
            "r8 = []",
            "r9 = 0",
            "r8[0] = r0",
            "r9 = 1",
            "r8[1] = r1",
            "r9 = 2",
            "ACCU = Object.values",
            "r10 = Object.values",
            "r12 = Object.values(r2)",
            "for (const item of r12) {",
            "  r8[r9] = item",
            "  r9 += 1",
            "}",
            "r3 = r8",
            "return r8.length",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            ["return [r0, r1, ...Object.values(r2)].length"],
        )

    def test_compacts_fixed_array_builder(self) -> None:
        lines = [
            "r3 = []",
            "r4 = 0",
            "r3[0] = arg0",
            "r4 = 1",
            "r3[1] = (arg0 + 1)",
            "r0 = r3",
            "r3 = context_slot[3]",
            "r1 = new Pair(...r0)",
            "return Math.max.call(Math, ...r0)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r0 = [arg0, (arg0 + 1)]",
                "r1 = new Pair(...r0)",
                "return Math.max(...r0)",
            ],
        )

    def test_drops_dead_pure_accu_load_before_register_store(self) -> None:
        lines = [
            "ACCU = 0",
            "r0 = 0",
            "ACCU = arg0.name",
            "r1 = arg0.name",
            "return r1",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return arg0.name"])

    def test_keeps_effectful_accu_expression_statement(self) -> None:
        lines = [
            "ACCU = fn.call(arg0)",
            "return undefined",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["fn.call(arg0)", "return undefined"])

    def test_substitutes_accu_in_keyed_property_read(self) -> None:
        lines = [
            "ACCU = 0",
            "ACCU = arg0[ACCU]",
            "r0 = ACCU",
            "ACCU = arg1",
            "ACCU = arg0[ACCU]",
            "r1 = ACCU",
            "ACCU = r1",
            "ACCU = (r0 + ACCU)",
            "return ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["return (arg0[0] + arg0[arg1])"])

    def test_keeps_keyed_property_accu_when_next_condition_reads_it(self) -> None:
        lines = [
            "ACCU = 0",
            "ACCU = r2[ACCU]",
            "r2 = ACCU",
            "if (!(isNullish(ACCU))) {",
            "  ACCU = r2.length",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertIn("ACCU = r2[0]", simplified)
        self.assertIn("r2 = r2[0]", simplified)

    def test_compacts_keyed_property_read_with_saved_key_register(self) -> None:
        lines = [
            "ACCU = context_slot[2]",
            "r2 = context_slot[2]",
            "ACCU = this[ACCU]",
            "r3 = ACCU",
            "return r3",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r3 = this[context_slot[2]]",
                "return r3",
            ],
        )

    def test_substitutes_accu_in_property_assignment(self) -> None:
        lines = [
            "ACCU = arg0.count",
            "ACCU = (ACCU + 1)",
            "arg0.count = ACCU",
            "ACCU = true",
            "arg0.seen = ACCU",
            "ACCU = arg0.count",
            "return ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "arg0.count = (arg0.count + 1)",
                "arg0.seen = true",
                "return arg0.count",
            ],
        )

    def test_does_not_inline_register_alias_to_accu(self) -> None:
        lines = [
            "ACCU = arg0",
            "if (!(isNullish(ACCU))) {",
            "}",
            "else {",
            "  ACCU = arg2",
            "}",
            "r0 = ACCU",
            "if (truthy(ACCU)) {",
            "  ACCU = arg1",
            "  if (truthy(ACCU)) {",
            "    ACCU = r0.value",
            "    return ACCU",
            "  }",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertIn("  return r0.value", simplified)
        self.assertIn("if (truthy(r0) && truthy(arg1)) {", simplified)
        self.assertNotIn("ACCU = ACCU.value", simplified)

    def test_recovers_nullish_assignment_to_register(self) -> None:
        lines = [
            "ACCU = arg0",
            "if (!(isNullish(ACCU))) {",
            "}",
            "else {",
            "  ACCU = arg2",
            "}",
            "r0 = ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r0 = (isNullish(arg0) ? arg2 : arg0)"])

    def test_recovers_optional_chain_to_accu_expression(self) -> None:
        lines = [
            "ACCU = arg0",
            "r2 = arg0",
            "if (!(isNullish(ACCU))) {",
            "  ACCU = r2.profile",
            "  r2 = r2.profile",
            "  if (!(isNullish(ACCU))) {",
            "    ACCU = r2.address",
            "    r2 = r2.address",
            "    if (!(isNullish(ACCU))) {",
            "      ACCU = r2.city",
            "    }",
            "    else {",
            "      ACCU = undefined",
            "    }",
            "  }",
            "  else {",
            "    ACCU = undefined",
            "  }",
            "}",
            "else {",
            "  ACCU = undefined",
            "}",
            "r0 = ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r0 = arg0?.profile?.address?.city"])

    def test_recovers_or_fallback_assignment(self) -> None:
        lines = [
            "ACCU = arg0?.tags?.[0]?.length",
            "if (!(truthy(ACCU))) {",
            "  ACCU = 0",
            "}",
            "r1 = ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r1 = (arg0?.tags?.[0]?.length || 0)"])

    def test_recovers_undefined_default_assignment_with_else(self) -> None:
        lines = [
            "ACCU = arg0",
            "if (!(ACCU !== undefined)) {",
            "  ACCU = 1",
            "}",
            "else {",
            "  ACCU = arg0",
            "}",
            "r0 = ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r0 = (arg0 === undefined ? 1 : arg0)"])

    def test_recovers_undefined_default_and_rewrites_next_accu_consumer(self) -> None:
        lines = [
            "ACCU = arg0",
            "if (!(ACCU !== undefined)) {",
            "  ACCU = 1",
            "}",
            "else {",
            "  ACCU = arg0",
            "}",
            "r0 = ACCU",
            "ACCU = (this.n + ACCU)",
            "return ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r0 = (arg0 === undefined ? 1 : arg0)",
                "return (this.n + r0)",
            ],
        )

    def test_recovers_undefined_default_assignment_without_else(self) -> None:
        lines = [
            "ACCU = arg0.a",
            "if (!(ACCU !== undefined)) {",
            "  ACCU = 1",
            "}",
            "r0 = ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ["r0 = (arg0.a === undefined ? 1 : arg0.a)"])

    def test_recovers_undefined_default_with_interleaved_receiver_save(self) -> None:
        lines = [
            "ACCU = arg0.a",
            "r8 = arg0",
            "if (!(ACCU !== undefined)) {",
            "  ACCU = 1",
            "}",
            "r0 = ACCU",
            "return r8.b",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r0 = (arg0.a === undefined ? 1 : arg0.a)",
                "return arg0.b",
            ],
        )

    def test_does_not_recover_undefined_default_across_effectful_save(self) -> None:
        lines = [
            "ACCU = arg0.a",
            "r8 = fn()",
            "if (!(ACCU !== undefined)) {",
            "  ACCU = 1",
            "}",
            "r0 = ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertIn("ACCU = arg0.a", simplified)
        self.assertIn("r8 = fn()", simplified)

    def test_recovers_or_fallback_return(self) -> None:
        lines = [
            "ACCU = r0.value",
            "if (!(truthy(ACCU))) {",
            '  ACCU = "missing"',
            "}",
            "return ACCU",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(simplified, ['return (r0.value || "missing")'])

    def test_combines_nested_truthy_ifs(self) -> None:
        lines = [
            "if (truthy(r0)) {",
            "  if (truthy(arg1)) {",
            "    return r0.value",
            "  }",
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "if (truthy(r0) && truthy(arg1)) {",
                "  return r0.value",
                "}",
            ],
        )

    def test_rewrites_accu_truthy_condition_after_duplicate_store(self) -> None:
        lines = [
            "ACCU = r2.exec(arg0)",
            "r0 = r2.exec(arg0)",
            "if (!(truthy(ACCU))) {",
            '  return ("bad:" + String(arg0))',
            "}",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "r0 = r2.exec(arg0)",
                "if (!truthy(r0)) {",
                '  return ("bad:" + String(arg0))',
                "}",
            ],
        )

    def test_inlines_generator_resume_mode_into_smi_switch_comment(self) -> None:
        lines = [
            "ACCU = _GeneratorGetResumeMode(r0)",
            "// SwitchOnSmiNoFeedback ACCU [3], [2], [0] { 0: @39, 1: @36 }",
            "throw r1",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                "// SwitchOnSmiNoFeedback _GeneratorGetResumeMode(r0) [3], [2], [0] { 0: @39, 1: @36 }",
                "throw r1",
            ],
        )

    def test_preserves_unused_placeholder_property_read_without_accu(self) -> None:
        lines = [
            'ACCU = r2["<undefined: segmentfault, might outside scope>"]',
            "return r2.value",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                'r2["<undefined: segmentfault, might outside scope>"]',
                "return r2.value",
            ],
        )

    def test_preserves_diagnostic_placeholder_property_read_without_accu(self) -> None:
        lines = [
            'ACCU = r2["<undefined: segmentfault, might outside scope; object_chunk_offset=0xde48 tagged_chunk_offset=0xde49>"]',
            "return r2.value",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                'r2["<undefined: segmentfault, might outside scope; object_chunk_offset=0xde48 tagged_chunk_offset=0xde49>"]',
                "return r2.value",
            ],
        )

    def test_inlines_simple_accu_literal_into_next_assignment(self) -> None:
        lines = [
            'ACCU = ":"',
            "r3 = (context_slot[2].call(undefined, \"x\", ...r0) + ACCU)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            ['r3 = (context_slot[2].call(undefined, "x", ...r0) + ":")'],
        )

    def test_recovers_two_case_switch_assignment_as_conditional_value(self) -> None:
        lines = [
            "ACCU = undefined",
            "r4 = undefined",
            "ACCU = 1",
            "ACCU = (arg2 === ACCU)",
            "r13 = arg2",
            "if (!(truthy(ACCU))) {",
            "  ACCU = 2",
            "  ACCU = (r13 === ACCU)",
            "  if (!(truthy(ACCU))) {",
            "    // goto offset_332",
            "  }",
            "  else {",
            '    ACCU = "two"',
            '    r4 = "two"',
            "  }",
            "}",
            "else {",
            '  ACCU = "one"',
            '  r4 = "one"',
            "  // goto offset_335",
            "}",
            'ACCU = "other"',
            'r4 = "other"',
            "r13 = String(r4)",
        ]

        simplified = simplify_lines(lines, recover_structures=True)

        self.assertEqual(
            simplified,
            [
                'r4 = ((arg2 === 1) ? "one" : ((arg2 === 2) ? "two" : "other"))',
                "r13 = String(r4)",
            ],
        )


if __name__ == "__main__":
    unittest.main()
