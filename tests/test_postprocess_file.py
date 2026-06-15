from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECOMPILER = ROOT / "decompiler"
if str(DECOMPILER) not in sys.path:
    sys.path.insert(0, str(DECOMPILER))

from postprocess_file import (
    compact_file_register_concat_returns,
    normalize_unique_string_function_names,
    postprocess_level4_file,
    recover_context_slot_closure_names,
)


class PostprocessFileTests(unittest.TestCase):
    def test_compacts_register_concat_chain_after_function_assembly(self) -> None:
        text = "\n".join(
            [
                "function run(arg0) {",
                '  r3 = collect("x", ...r0)',
                '  r3 += ":"',
                "  r3 += r2",
                '  r3 += ":"',
                "  return (r3 + r1.sum())",
                "}",
            ]
        )

        recovered = compact_file_register_concat_returns(text)

        self.assertIn(
            'return (collect("x", ...r0) + ":" + r2 + ":" + r1.sum())',
            recovered,
        )
        self.assertNotIn("r3 +", recovered)

    def test_recovers_context_slot_closure_name_inside_same_function(self) -> None:
        text = "\n".join(
            [
                "function bytecode() {",
                "  r2 = create_closure(Counter)",
                "  script_context[3] = r2",
                "  script_context[4] = new context_slot[3](2)",
                "  return context_slot[4].inc(3)",
                "}",
            ]
        )

        recovered = recover_context_slot_closure_names(text)

        self.assertIn("script_context[4] = new Counter(2)", recovered)
        self.assertIn("return context_slot[4].inc(3)", recovered)

    def test_recovers_direct_script_context_closure_assignment(self) -> None:
        text = "\n".join(
            [
                "function bytecode() {",
                "  script_context[2] = create_closure(seq)",
                "  return context_slot[2](3)",
                "}",
            ]
        )

        recovered = recover_context_slot_closure_names(text)

        self.assertIn("return seq(3)", recovered)

    def test_does_not_recover_after_non_closure_slot_overwrite(self) -> None:
        text = "\n".join(
            [
                "function bytecode() {",
                "  script_context[2] = create_closure(seq)",
                "  script_context[2] = 1",
                "  return context_slot[2](3)",
                "}",
            ]
        )

        recovered = recover_context_slot_closure_names(text)

        self.assertIn("return context_slot[2](3)", recovered)

    def test_does_not_recover_across_function_boundaries(self) -> None:
        text = "\n".join(
            [
                "function first() {",
                "  script_context[2] = create_closure(seq)",
                "}",
                "",
                "function second() {",
                "  return context_slot[2](3)",
                "}",
            ]
        )

        recovered = recover_context_slot_closure_names(text)

        self.assertIn("return context_slot[2](3)", recovered)

    def test_recovers_context_slot_after_ensure_defined(self) -> None:
        text = "\n".join(
            [
                "function run(arg0) {",
                '  ensureDefined("Pair")',
                "  r1 = new context_slot[3](...arg0)",
                "  return r1.sum()",
                "}",
            ]
        )

        recovered = recover_context_slot_closure_names(text)

        self.assertIn("r1 = new Pair(...arg0)", recovered)

    def test_ensure_defined_requires_identifier_name(self) -> None:
        text = "\n".join(
            [
                "function run(arg0) {",
                '  ensureDefined("<undefined: segmentfault>")',
                "  return context_slot[3](...arg0)",
                "}",
            ]
        )

        recovered = recover_context_slot_closure_names(text)

        self.assertIn("return context_slot[3](...arg0)", recovered)

    def test_normalizes_unique_v8_string_function_names(self) -> None:
        text = "\n".join(
            [
                "function String_9_parseLine(arg0) {",
                "  return arg0",
                "}",
                "",
                "function bytecode() {",
                "  return create_closure(String_9_parseLine)",
                "}",
            ]
        )

        recovered = normalize_unique_string_function_names(text)

        self.assertIn("function parseLine(arg0) {", recovered)
        self.assertIn("return create_closure(parseLine)", recovered)
        self.assertNotIn("String_9_parseLine", recovered)

    def test_level4_file_postprocess_renames_recovered_context_slot_name(self) -> None:
        text = "\n".join(
            [
                "function bytecode() {",
                "  r2 = create_closure(String_7_Counter)",
                "  script_context[3] = r2",
                "  script_context[4] = new context_slot[3](2)",
                "  return context_slot[4].inc(3)",
                "}",
                "",
                "function String_7_Counter(arg0) {",
                "  return arg0",
                "}",
            ]
        )

        recovered = postprocess_level4_file(text)

        self.assertIn("script_context[4] = new Counter(2)", recovered)
        self.assertIn("function Counter(arg0) {", recovered)
        self.assertNotIn("String_7_Counter", recovered)

    def test_keeps_duplicate_v8_string_function_names(self) -> None:
        text = "\n".join(
            [
                "function String_3_Box(arg0) {",
                "  return arg0",
                "}",
                "",
                "function String_3_Box() {",
                "  return undefined",
                "}",
                "",
                "function bytecode() {",
                "  return create_closure(String_3_Box)",
                "}",
            ]
        )

        recovered = normalize_unique_string_function_names(text)

        self.assertIn("function String_3_Box(arg0) {", recovered)
        self.assertIn("function String_3_Box() {", recovered)
        self.assertIn("return create_closure(String_3_Box)", recovered)

    def test_keeps_anonymous_string_zero_name(self) -> None:
        text = "\n".join(
            [
                "function String_0(arg0) {",
                "  return arg0",
                "}",
                "",
                "function bytecode() {",
                "  return create_closure(String_0)",
                "}",
            ]
        )

        recovered = normalize_unique_string_function_names(text)

        self.assertIn("function String_0(arg0) {", recovered)
        self.assertIn("return create_closure(String_0)", recovered)


if __name__ == "__main__":
    unittest.main()
