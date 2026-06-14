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


if __name__ == "__main__":
    unittest.main()
