from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUND_DIR = ROOT / "tests" / "decomp_rounds"
if str(ROUND_DIR) not in sys.path:
    sys.path.insert(0, str(ROUND_DIR))

from analyze_round import (
    classify_decompile_status,
    parse_header_diagnostics,
    unresolved_current_ro_objects,
    unresolved_object_addresses,
    unresolved_object_chunk_offsets,
    unresolved_object_suffixes,
)


class AnalyzeRoundTests(unittest.TestCase):
    def test_parse_matching_cached_data_header(self) -> None:
        diagnostics = parse_header_diagnostics(
            """
Cached data header:
  magic: 0xc0de0689 (expected 0xc0de0689)
  version_hash: 0x2b2c7714 (expected 0x2b2c7714)
  flags_hash: 0xdc93751f (expected 0xdc93751f)
  read_only_snapshot_checksum: 0x436e38a3 (expected 0x436e38a3)
  payload_length: 624 (max 624)
"""
        )

        self.assertEqual(diagnostics["header_mismatch"], "ok")
        self.assertEqual(diagnostics["ro_snapshot"], "ok")

    def test_parse_node_embedder_snapshot_mismatch(self) -> None:
        diagnostics = parse_header_diagnostics(
            """
Cached data header:
  magic: 0xc0de0688 (expected 0xc0de0689) mismatch
  version_hash: 0x2b2c7714 (expected 0x2b2c7714)
  flags_hash: 0x1c7c619b (expected 0xdc93751f) mismatch
  read_only_snapshot_checksum: 0xd31c4342 (expected 0x436e38a3) mismatch
  payload_length: 856 (max 856)
"""
        )

        self.assertEqual(
            diagnostics["header_mismatch"],
            "magic,flags_hash,ro_snapshot",
        )
        self.assertEqual(diagnostics["ro_snapshot"], "mismatch")

    def test_missing_cached_data_header_is_not_applicable(self) -> None:
        diagnostics = parse_header_diagnostics("disasm failed before header parse")

        self.assertEqual(diagnostics["header_mismatch"], "n/a")
        self.assertEqual(diagnostics["ro_snapshot"], "n/a")

    def test_classifies_round_failure_placeholders(self) -> None:
        self.assertEqual(
            classify_decompile_status("// disasm failed for sample.jsc\n"),
            "disasm_failed",
        )
        self.assertEqual(
            classify_decompile_status("// decompile failed for sample.txt\n"),
            "decompile_failed",
        )
        self.assertEqual(
            classify_decompile_status("// disasm skipped for sample.jsc\n"),
            "disasm_skipped",
        )
        self.assertEqual(
            classify_decompile_status("// input jsc not found: sample.jsc\n"),
            "input_missing",
        )
        self.assertEqual(classify_decompile_status("function ok() {}\n"), "ok")

    def test_extracts_unique_unresolved_object_addresses(self) -> None:
        text = (
            """
           1: 0x332de880a701 <undefined: segmentfault, might outside scope>
           2: 0x332de880a701 <undefined: segmentfault, might outside scope>
!0x332de880a701: segmentfault, disassemble stop
"""
            "!0x332de880d479: segmentfault while discovering object, skipped "
            "(ro_page=0 object_chunk_offset=0xd478 tagged_chunk_offset=0xd479 "
            "area_offset=0xd468) current_ro_object=[0xd468,0xd480) delta=0x10 "
            "hit=inside\n"
            """
           3: 0x332de880ffee <String[4]: #fine>
"""
        )

        self.assertEqual(
            unresolved_object_addresses(text),
            {"0x332de880a701", "0x332de880d479"},
        )
        self.assertEqual(unresolved_object_suffixes(text), {"a701", "d479"})
        self.assertEqual(unresolved_object_chunk_offsets(text), {"0xd478"})
        self.assertEqual(
            unresolved_current_ro_objects(text),
            {"inside+0x10@[0xd468,0xd480)"},
        )


if __name__ == "__main__":
    unittest.main()
