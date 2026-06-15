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


if __name__ == "__main__":
    unittest.main()
