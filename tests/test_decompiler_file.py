from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
from decompiler import decompile_file, decompile_objects
from disassembler.disassembler import parse_disassembly_file
from disassembler.structured import disassembly_to_dict
from decompiler.context import DecompilerContext
from decompiler.objects import V8Address, V8BytecodeArray, V8SharedFunctionInfo
from decompiler.structured import load_structured_objects


class DecompilerFileTests(unittest.TestCase):
    def test_module_cli_reads_structured_json_in_linear_mode(self) -> None:
        document = disassembly_to_dict(
            parse_disassembly_file(ROOT / "samples" / "main.d8.jsc")
        )
        path = ROOT / "tests" / "tmp_cli_disassembly.json"
        try:
            path.write_text(json.dumps(document), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "decompiler",
                    str(path),
                    "--linear",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("function add(arg0, arg1)", result.stdout)
        self.assertIsNotNone(
            re.search(r"^\s*\[\s*0\]\s", result.stdout, re.MULTILINE)
        )

    def test_module_cli_defaults_to_source_recovery(self) -> None:
        document = disassembly_to_dict(
            parse_disassembly_file(ROOT / "samples" / "main.d8.jsc")
        )
        path = ROOT / "tests" / "tmp_cli_source.json"
        try:
            path.write_text(json.dumps(document), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "decompiler", str(path)],
                cwd=ROOT,
                check=True,
                text=True,
                stdout=subprocess.PIPE,
            )
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("function add(arg0, arg1)", result.stdout)
        self.assertIsNone(
            re.search(r"^\s*\[\s*0\]\s", result.stdout, re.MULTILINE)
        )

    def test_module_cli_rejects_removed_level_option(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "decompiler",
                str(ROOT / "samples" / "main.d8.jsc.txt"),
                "--level",
                "4",
            ],
            cwd=ROOT,
            check=False,
            text=True,
            stderr=subprocess.PIPE,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrecognized arguments: --level 4", result.stderr)

    def test_complex_fixture_recovers_object_literals_and_closures(self) -> None:
        versions = (
            "10.2.154.26",
            "11.3.244.8",
            "12.4.254.21",
            "13.6.233.10",
        )
        for version in versions:
            with self.subTest(version=version):
                parsed = parse_disassembly_file(
                    ROOT
                    / "tests"
                    / "fixtures"
                    / f"complex-closures-{version}.jsc"
                )
                document = disassembly_to_dict(parsed)
                output = decompile_objects(
                    load_structured_objects(document)
                )

                self.assertEqual(document["metadata"]["v8_version"], version)
                self.assertIn(
                    "[{ enabled: true, value: 3 }, "
                    "{ enabled: false, value: 8 }, { enabled: true }]",
                    output,
                )
                self.assertIn("function createCounter(arg0 = 0)", output)
                self.assertIn("\n  function increment(arg0 = 1)", output)
                self.assertIn("\n  function read()", output)
                self.assertNotIn("\nfunction increment(", output)
                self.assertNotIn("\nfunction read()", output)
                self.assertIn("return value", output)
                self.assertNotIn("context_slot[2]", output)
                self.assertNotIn("arg0 === undefined", output)
                self.assertNotIn("ensureDefined(", output)
                self.assertNotIn("DeclareGlobals(", output)
                self.assertIn("let value = arg0;", output)
                self.assertIn("value += arg0", output)
                self.assertEqual(output.count("?.enabled"), 1)
                self.assertEqual(output.count("??"), 1)
                if version in {"12.4.254.21", "13.6.233.10"}:
                    self.assertIn("for (const item of arg0)", output)
                self.assertIn("return { increment, read }", output)
                self.assertNotIn("pushContext(create_block_context", output)
                self.assertNotIn("value = HOLE", output)
                self.assertIn("counter = createCounter(2)", output)
                self.assertIn("output = mapValues(", output)
                self.assertEqual(output.count("createCounter(2)"), 1)
                self.assertEqual(output.count("counter.read()"), 1)
                self.assertIn("r1 = globalThis", output)
                self.assertIn(
                    "r2 = { output, current: counter.read() }",
                    output,
                )
                self.assertIn("r1.result = r2", output)
                self.assertNotIn("r2.current = counter.read()", output)
                self.assertEqual(
                    output.count(
                        "mapValues([{ enabled: true, value: 3 }, "
                    ),
                    1,
                )
                self.assertIn("let counter, output;", output)
                self.assertNotIn("function anonymous_1()", output)
                self.assertNotIn("r2.increment = increment", output)
                self.assertNotIn("r2.read = read", output)
                self.assertNotIn("create_closure(increment)", output)
                self.assertNotIn("create_closure(read)", output)

                names = re.findall(
                    r"^\s*function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(",
                    output,
                    flags=re.MULTILINE,
                )
                self.assertEqual(len(names), len(set(names)))
                for name in (
                    "createCounter",
                    "mapValues",
                    "increment",
                    "read",
                ):
                    self.assertIn(name, output)

    def test_structured_closure_recovers_nesting_and_context_name(self) -> None:
        document = disassembly_to_dict(
            parse_disassembly_file(
                ROOT / "tests" / "fixtures" / "closure-13.6.233.10.jsc"
            )
        )
        path = ROOT / "tests" / "tmp_closure_disassembly.json"
        try:
            path.write_text(json.dumps(document), encoding="utf-8")
            output = decompile_file(path, linear=True)
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("function makeAdder(base) {", output)
        self.assertIn("\n  function add(arg0) {", output)
        self.assertNotIn("\nfunction add(arg0) {", output)
        self.assertIn("ACCU = base", output)
        self.assertIn("base = ACCU", output)
        self.assertNotIn("context_slot[2]", output)

    def test_anonymous_function_names_are_unique(self) -> None:
        first_bytecode = V8BytecodeArray(0x1000, "BytecodeArray", [])
        second_bytecode = V8BytecodeArray(0x2000, "BytecodeArray", [])
        first = V8SharedFunctionInfo(0x3000, "SharedFunctionInfo", [])
        second = V8SharedFunctionInfo(0x4000, "SharedFunctionInfo", [])
        first.name_value = ""
        second.name_value = ""
        first.trusted_function_data = V8Address(first_bytecode.address)
        second.trusted_function_data = V8Address(second_bytecode.address)

        context = DecompilerContext(
            [first_bytecode, second_bytecode, first, second]
        )

        self.assertEqual(context.get_function_name(first), "anonymous_1")
        self.assertEqual(context.get_function_name(second), "anonymous_2")

    def test_structured_json_bypasses_text_object_parser(self) -> None:
        document = disassembly_to_dict(
            parse_disassembly_file(ROOT / "samples" / "main.d8.jsc")
        )
        path = ROOT / "tests" / "tmp_disassembly.json"
        try:
            path.write_text(json.dumps(document), encoding="utf-8")
            with mock.patch(
                "decompiler.core.parse_objects",
                side_effect=AssertionError("text parser must not be used for JSON"),
            ):
                output = decompile_file(path, linear=True)
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("function add(arg0, arg1)", output)
        self.assertIn("function listSum(arg0)", output)
        self.assertIn('"console"', output)

    def test_non_utf8_disassembly_input_is_decoded_lossily(self) -> None:
        dump = (
            b"0x1000: [BytecodeArray]\n"
            b"Parameter count 1\n"
            b"Register count 0\n"
            b"Frame size 0\n"
            b"    0 S> 0x1000 @    0 : b3                Return\n"
            b"Constant pool (size = 0)\n"
            b"Handler Table (size = 0)\n"
            b"Source Position Table (size = 0)\n"
            b"0x1001: [String]: #bad-\xc5\n"
            b"0x1002: [String]\n"
        )
        path = ROOT / "tests" / "tmp_non_utf8_disasm.txt"
        try:
            path.write_bytes(dump)
            output = decompile_file(path, linear=True)
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("function bytecode_000000001000()", output)
        self.assertIn("return ACCU", output)

    def test_try_catch_prefix_guard_is_structured_instead_of_raw_goto(self) -> None:
        dump = (
            "0x1000: [BytecodeArray]\n"
            "Parameter count 1\n"
            "Register count 2\n"
            "Frame size 16\n"
            "         0x1000 @    0 : 17 03             LdaCurrentContextSlot [3]\n"
            "         0x1002 @    2 : a1 12             JumpIfToBooleanFalse [18] (0x1014 @ 20)\n"
            "         0x1004 @    4 : 0e                LdaUndefined\n"
            "         0x1005 @    5 : 27 04             StaCurrentContextSlot [4]\n"
            "         0x1007 @    7 : 93 0d             Jump [13] (0x1014 @ 20)\n"
            "         0x1009 @    9 : cd                Star1\n"
            "         0x100a @   10 : 8b f8 00          CreateCatchContext r1, [0]\n"
            "         0x100d @   13 : ce                Star0\n"
            "         0x100e @   14 : 1c f8             PushContext r1\n"
            "         0x1010 @   16 : 0e                LdaUndefined\n"
            "         0x1011 @   17 : 27 05             StaCurrentContextSlot [5]\n"
            "         0x1013 @   19 : 1d f8             PopContext r1\n"
            "         0x1014 @   20 : 0e                LdaUndefined\n"
            "         0x1015 @   21 : b3                Return\n"
            "Constant pool (size = 0)\n"
            "Handler Table (size = 16)\n"
            "   from   to       hdlr (prediction,   data)\n"
            "  (   4,   7)  ->     9 (prediction=1, data=0)\n"
            "Source Position Table (size = 0)\n"
        )
        path = ROOT / "tests" / "tmp_try_guard_disasm.txt"
        try:
            path.write_text(dump, encoding="utf-8")
            output = decompile_file(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertNotIn("goto offset_", output)
        self.assertIn("if (truthy(context_slot[3])) {", output)
        self.assertIn("try {", output)
        self.assertIn("} catch (e) {", output)

    def test_try_catch_short_circuit_guard_preserves_alternate_suffix(self) -> None:
        dump = (
            "0x1000: [BytecodeArray]\n"
            "Parameter count 1\n"
            "Register count 3\n"
            "Frame size 24\n"
            "         0x1000 @    0 : 17 05             LdaCurrentContextSlot [5]\n"
            "         0x1002 @    2 : a0 10             JumpIfToBooleanTrue [16] (0x1012 @ 18)\n"
            "         0x1004 @    4 : 17 02             LdaCurrentContextSlot [2]\n"
            "         0x1006 @    6 : a1 26             JumpIfToBooleanFalse [38] (0x102c @ 44)\n"
            "         0x1012 @   18 : 1b ff f7          Mov <context>, r2\n"
            "         0x1015 @   21 : 0e                LdaUndefined\n"
            "         0x1016 @   22 : 27 04             StaCurrentContextSlot [4]\n"
            "         0x1018 @   24 : 93 0e             Jump [14] (0x1026 @ 38)\n"
            "         0x101a @   26 : cd                Star1\n"
            "         0x101b @   27 : 8b f8 00          CreateCatchContext r1, [0]\n"
            "         0x101e @   30 : ce                Star0\n"
            "         0x101f @   31 : 1c f8             PushContext r1\n"
            "         0x1021 @   33 : 0e                LdaUndefined\n"
            "         0x1022 @   34 : 27 06             StaCurrentContextSlot [6]\n"
            "         0x1024 @   36 : 1d f8             PopContext r1\n"
            "         0x1026 @   38 : 93 0e             Jump [14] (0x1034 @ 52)\n"
            "         0x102c @   44 : 17 07             LdaCurrentContextSlot [7]\n"
            "         0x102e @   46 : ce                Star0\n"
            "         0x102f @   47 : 68 f9 00          CallUndefinedReceiver0 r0, [0]\n"
            "         0x1034 @   52 : 0e                LdaUndefined\n"
            "         0x1035 @   53 : b3                Return\n"
            "Constant pool (size = 0)\n"
            "Handler Table (size = 16)\n"
            "   from   to       hdlr (prediction,   data)\n"
            "  (  21,  24)  ->    26 (prediction=1, data=0)\n"
            "Source Position Table (size = 0)\n"
        )
        path = ROOT / "tests" / "tmp_try_alternate_disasm.txt"
        try:
            path.write_text(dump, encoding="utf-8")
            output = decompile_file(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertNotIn("goto offset_", output)
        self.assertIn("if (truthy(context_slot[5]) || truthy(context_slot[2])) {", output)
        self.assertIn("} else {", output)
        self.assertIn("context_slot[7]()", output)

    def test_jump_if_constant_branches_are_structured(self) -> None:
        dump = (
            "0x1000: [BytecodeArray]\n"
            "Parameter count 1\n"
            "Register count 0\n"
            "Frame size 0\n"
            "         0x1000 @    0 : 17 01             LdaCurrentContextSlot [1]\n"
            "         0x1002 @    2 : 9b 00             JumpIfFalseConstant [0] (0x100a @ 10)\n"
            "         0x1004 @    4 : 11                LdaTrue\n"
            "         0x1005 @    5 : 27 02             StaCurrentContextSlot [2]\n"
            "         0x1006 @    6 : 93 07             Jump [7] (0x100d @ 13)\n"
            "         0x100a @   10 : 12                LdaFalse\n"
            "         0x100b @   11 : 27 02             StaCurrentContextSlot [2]\n"
            "         0x100d @   13 : 0e                LdaUndefined\n"
            "         0x100e @   14 : b3                Return\n"
            "Constant pool (size = 0)\n"
            "Handler Table (size = 0)\n"
            "Source Position Table (size = 0)\n"
        )
        path = ROOT / "tests" / "tmp_jump_if_constant_disasm.txt"
        try:
            path.write_text(dump, encoding="utf-8")
            output = decompile_file(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertNotIn("goto offset_", output)
        self.assertIn("if (truthy(context_slot[1])) {", output)
        self.assertIn("else {", output)
        self.assertIn("context_slot[2] = true", output)
        self.assertIn("context_slot[2] = false", output)

    def test_constant_jump_chain_preserves_fallthrough_cases(self) -> None:
        dump = (
            "0x1000: [BytecodeArray]\n"
            "Parameter count 1\n"
            "Register count 1\n"
            "Frame size 8\n"
            "         0x1000 @    0 : 17 24             LdaCurrentContextSlot [36]\n"
            "         0x1002 @    2 : ce                Star0\n"
            "         0x1003 @    3 : 13 00             LdaConstant [0]\n"
            "         0x1005 @    5 : 74 f9 00          TestEqualStrict r0, [0]\n"
            "         0x1008 @    8 : 9a 04             JumpIfTrueConstant [4] (0x101e @ 30)\n"
            "         0x100a @   10 : 13 01             LdaConstant [1]\n"
            "         0x100c @   12 : 74 f9 00          TestEqualStrict r0, [0]\n"
            "         0x100f @   15 : 9a 05             JumpIfTrueConstant [5] (0x1026 @ 38)\n"
            "         0x1011 @   17 : 93 1b             Jump [27] (0x102c @ 44)\n"
            "         0x101e @   30 : 13 03             LdaConstant [3]\n"
            "         0x1020 @   32 : 27 24             StaCurrentContextSlot [36]\n"
            "         0x1022 @   34 : 93 0e             Jump [14] (0x1030 @ 48)\n"
            "         0x1026 @   38 : 13 04             LdaConstant [4]\n"
            "         0x1028 @   40 : 27 24             StaCurrentContextSlot [36]\n"
            "         0x102a @   42 : 93 06             Jump [6] (0x1030 @ 48)\n"
            "         0x102c @   44 : 13 02             LdaConstant [2]\n"
            "         0x102e @   46 : 27 24             StaCurrentContextSlot [36]\n"
            "         0x1030 @   48 : 17 24             LdaCurrentContextSlot [36]\n"
            "         0x1032 @   50 : b3                Return\n"
            "Constant pool (size = 5)\n"
            "           0: 0x2000 <String[5]: #zh-CN>\n"
            "           1: 0x2001 <String[5]: #zh-TW>\n"
            "           2: 0x2002 <String[4]: #Base>\n"
            "           3: 0x2003 <String[7]: #zh-Hans>\n"
            "           4: 0x2004 <String[7]: #zh-Hant>\n"
            "Handler Table (size = 0)\n"
            "Source Position Table (size = 0)\n"
        )
        path = ROOT / "tests" / "tmp_constant_jump_chain_disasm.txt"
        try:
            path.write_text(dump, encoding="utf-8")
            output = decompile_file(path)
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("context_slot[36] = Const[2]", output)
        self.assertIn("context_slot[36] = Const[3]", output)
        self.assertIn("context_slot[36] = Const[4]", output)


if __name__ == "__main__":
    unittest.main()
