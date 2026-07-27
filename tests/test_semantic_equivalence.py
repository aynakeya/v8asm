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
    def assert_fixture_equivalent(self, name: str) -> None:
        source = (FIXTURES / f"{name}.js").read_text(encoding="utf-8")
        recovered = decompile_fixture(name)
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

    def test_short_circuit_evaluation(self) -> None:
        self.assert_fixture_equivalent("short-circuit")

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

    def test_context_binding_provenance_is_explicit(self) -> None:
        recovered = decompile_fixture("context-depth")
        self.assertIn(
            "Captures: outerBias <- runContextDepth slot=2 defined@21, "
            "value <- middle slot=2 defined@18",
            recovered,
        )
        self.assertIn("function middle(arg0)", recovered)
        self.assertIn("let value;", recovered)


if __name__ == "__main__":
    unittest.main()
