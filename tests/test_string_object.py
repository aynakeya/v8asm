from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DECOMPILER = ROOT / "decompiler"
if str(DECOMPILER) not in sys.path:
    sys.path.insert(0, str(DECOMPILER))

from objects.string import V8String


class V8StringTests(unittest.TestCase):
    def test_hash_prefixed_string_value(self) -> None:
        obj = V8String(0x1001, "String", ["0x1001: [String]: #value"])

        obj.parse()

        self.assertEqual(obj.value, "value")

    def test_quoted_string_value(self) -> None:
        obj = V8String(
            0x1002,
            "String",
            ['0x1002: [String]: "line1\\x0aline2"'],
        )

        obj.parse()

        self.assertEqual(obj.value, "line1\nline2")


if __name__ == "__main__":
    unittest.main()
