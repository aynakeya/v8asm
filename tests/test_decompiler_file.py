from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECOMPILER = ROOT / "decompiler"
if str(DECOMPILER) not in sys.path:
    sys.path.insert(0, str(DECOMPILER))

from v8decompiler import decompile_file


class DecompilerFileTests(unittest.TestCase):
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
            output = decompile_file(path, level=1)
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
            output = decompile_file(path, level=4)
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
            output = decompile_file(path, level=4)
        finally:
            path.unlink(missing_ok=True)

        self.assertNotIn("goto offset_", output)
        self.assertIn("if (truthy(context_slot[5]) || truthy(context_slot[2])) {", output)
        self.assertIn("} else {", output)
        self.assertIn("context_slot[7]()", output)

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
            output = decompile_file(path, level=4)
        finally:
            path.unlink(missing_ok=True)

        self.assertIn("script_context[36] = Const[2]", output)
        self.assertIn("script_context[36] = Const[3]", output)
        self.assertIn("script_context[36] = Const[4]", output)


if __name__ == "__main__":
    unittest.main()
