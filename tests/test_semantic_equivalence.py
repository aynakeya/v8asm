from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from decompiler import decompile_objects
from decompiler.structured import load_structured_objects
from disassembler.disassembler import parse_disassembly_file
from disassembler.structured import disassembly_to_dict


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "semantic_fixtures"
NODE = shutil.which("node")

OBSERVE_SCRIPT = r"""
const vm = require("node:vm");
const fs = require("node:fs");
const source = fs.readFileSync(0, "utf8");
const sandbox = {};
vm.createContext(sandbox);

let report;
try {
  vm.runInContext(source, sandbox, { timeout: 2000 });
  report = { status: "ok", value: sandbox.__semantic_result };
} catch (error) {
  report = {
    status: "throw",
    name: error && error.name,
    message: error && error.message,
  };
}
process.stdout.write(JSON.stringify(report));
"""


def observe_javascript(source: str) -> dict[str, object]:
    if NODE is None:
        raise unittest.SkipTest("node is required for semantic equivalence tests")
    result = subprocess.run(
        [NODE, "-e", OBSERVE_SCRIPT],
        cwd=ROOT,
        input=source,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"node observer failed with {result.returncode}: {result.stderr}"
        )
    return json.loads(result.stdout)


def decompile_fixture(name: str) -> str:
    parsed = parse_disassembly_file(FIXTURES / f"{name}.jsc")
    document = disassembly_to_dict(parsed)
    return decompile_objects(
        load_structured_objects(document),
        runtime=True,
    )


class SemanticEquivalenceTests(unittest.TestCase):
    def assert_fixture_equivalent(self, name: str, cache_name: str | None = None) -> None:
        source = (FIXTURES / f"{name}.js").read_text(encoding="utf-8")
        recovered = decompile_fixture(cache_name or name)
        self.assertNotIn("// WARNING:", recovered)
        self.assertEqual(
            observe_javascript(recovered),
            observe_javascript(source),
            msg=f"semantic mismatch for {name}\n\n{recovered}",
        )

    def test_call_receiver_and_evaluation_order(self) -> None:
        self.assert_fixture_equivalent("call-order")

    def test_property_reads_preserve_getters_and_order(self) -> None:
        self.assert_fixture_equivalent("property-effects")

    def test_arithmetic_baseline(self) -> None:
        self.assert_fixture_equivalent("arithmetic")

    def test_numeric_conversion_and_updates(self) -> None:
        for cache in ("numeric-conversion", "numeric-conversion-10.2.154.26"):
            with self.subTest(cache=cache):
                self.assert_fixture_equivalent("numeric-conversion", cache)

    def test_delete_property_modes_and_keys(self) -> None:
        for cache in ("delete-property", "delete-property-10.2.154.26"):
            with self.subTest(cache=cache):
                self.assert_fixture_equivalent("delete-property", cache)

    def test_short_circuit_evaluation(self) -> None:
        self.assert_fixture_equivalent("short-circuit")

    def test_optional_chain_and_nullish_evaluation(self) -> None:
        self.assert_fixture_equivalent("optional-nullish")

    def test_default_rest_and_spread_arguments(self) -> None:
        self.assert_fixture_equivalent("default-rest-spread")

    def test_object_rest_and_spread_properties(self) -> None:
        for cache_name in (
            "object-rest-spread",
            "object-rest-spread-10.2.154.26",
            "object-rest-spread-11.3.244.8",
            "object-rest-spread-12.4.254.21",
        ):
            with self.subTest(cache=cache_name):
                self.assert_fixture_equivalent("object-rest-spread", cache_name)

    def test_literal_definition_order_and_function_kinds(self) -> None:
        self.assert_fixture_equivalent("literal-effects")

    def test_object_syntax_is_recovered_without_runtime_helpers(self) -> None:
        parsed = parse_disassembly_file(FIXTURES / "object-rest-spread.jsc")
        recovered = decompile_objects(load_structured_objects(disassembly_to_dict(parsed)))
        self.assertIn("get alphaValue() {", recovered)
        self.assertIn("...r6 } = r2", recovered)
        self.assertIn("[r0](arg0) {", recovered)
        for noise in ("ACCU", "ToName(", "define_literal_property(", "CopyDataProperties", "HOLE", "pushContext("):
            self.assertNotIn(noise, recovered)
        self.assertEqual(observe_javascript(recovered), observe_javascript((FIXTURES / "object-rest-spread.js").read_text()))

    def test_try_catch_finally_completion(self) -> None:
        self.assert_fixture_equivalent("try-finally")
        recovered = decompile_fixture("try-finally")
        self.assertIn("  } catch (error) {", recovered)
        self.assertIn("  } finally {", recovered)
        self.assertNotIn("  try {\n    try {", recovered)

    def test_try_catch_completion(self) -> None:
        self.assert_fixture_equivalent("try-catch")

    def test_closure_state_and_shadowing(self) -> None:
        self.assert_fixture_equivalent("closures")

    def test_context_depth_and_shadowing(self) -> None:
        self.assert_fixture_equivalent("context-depth")

    def test_lexical_initialization_and_closure_tdz(self) -> None:
        for cache_name in (
            "lexical-initialization", "lexical-initialization-10.2.154.26",
            "lexical-initialization-11.3.244.8", "lexical-initialization-12.4.254.21",
        ):
            with self.subTest(cache=cache_name):
                self.assert_fixture_equivalent("lexical-initialization", cache_name)

    def test_context_binding_provenance_is_explicit(self) -> None:
        recovered = decompile_fixture("context-depth")
        self.assertIn(
            "Captures: outerBias <- runContextDepth slot=2 defined@21, "
            "value <- middle slot=2 defined@18",
            recovered,
        )
        self.assertIn("function middle(arg0)", recovered)
        self.assertIn("let value = HOLE;", recovered)


if __name__ == "__main__":
    unittest.main()
