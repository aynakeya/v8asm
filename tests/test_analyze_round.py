from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUND_DIR = ROOT / "tests" / "decomp_rounds"
if str(ROUND_DIR) not in sys.path:
    sys.path.insert(0, str(ROUND_DIR))

from analyze_round import (
    classify_decompile_status,
    current_ro_objects_by_chunk_offset,
    infer_placeholder_name_hints,
    parse_header_diagnostics,
    parse_constant_pool_entries,
    score_text,
    summarize_placeholder_offsets,
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

    def test_raw_goto_score_ignores_preserved_comments(self) -> None:
        score = score_text(
            """
function sample() {
  // goto offset_12
  if (truthy(r0)) goto offset_20
  goto offset_30
}
"""
        )

        self.assertEqual(score["goto_comments"], 1)
        self.assertEqual(score["raw_goto"], 2)

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

    def test_groups_current_ro_objects_by_chunk_offset(self) -> None:
        text = (
            "!0x332de880d479: segmentfault while discovering object, skipped "
            "(ro_page=0 object_chunk_offset=0xd478 tagged_chunk_offset=0xd479 "
            "area_offset=0xd468) current_ro_object=[0xd468,0xd480) delta=0x10 "
            "hit=inside current_ro_short=0x1234 <String[7]: #collect>\n"
            "!0x332de880d479: segmentfault while discovering object, skipped "
            "(ro_page=0 object_chunk_offset=0xd478 tagged_chunk_offset=0xd479 "
            "area_offset=0xd460) current_ro_object=[0xd460,0xd468) delta=0x18 "
            "hit=after\n"
            "!0x332de880a701: segmentfault while discovering object, skipped "
            "(ro_page=0 object_chunk_offset=0xa700 tagged_chunk_offset=0xa701 "
            "area_offset=0xa6f0) current_ro_object=[0xa6f0,0xa708) delta=0x10 "
            "hit=inside\n"
        )

        self.assertEqual(
            current_ro_objects_by_chunk_offset(text),
            {
                "0xd478": {
                    "inside+0x10@[0xd468,0xd480) short=0x1234 <String[7]: #collect>",
                    "after+0x18@[0xd460,0xd468)",
                },
                "0xa700": {"inside+0x10@[0xa6f0,0xa708)"},
            },
        )

    def test_groups_shortprint_current_ro_object_by_chunk_offset(self) -> None:
        text = (
            '  //   [6] = "0x332de880de49 <undefined: segmentfault, '
            "might outside scope; object_chunk_offset=0xde48 "
            "tagged_chunk_offset=0xde49 area_offset=0xde38 "
            'current_ro_object=[0xde38,0xde50) delta=0x10 hit=inside>"\n'
        )

        self.assertEqual(
            unresolved_current_ro_objects(text),
            {"inside+0x10@[0xde38,0xde50)"},
        )
        self.assertEqual(
            current_ro_objects_by_chunk_offset(text),
            {"0xde48": {"inside+0x10@[0xde38,0xde50)"}},
        )

    def test_parses_function_scoped_constant_pool_entries(self) -> None:
        entries = parse_constant_pool_entries(
            """
function wrapper() {
  // Constant pool:
  //   [0] = [run, 0]
}

function run(arg0) {
  // Constant pool:
  //   [6] = "toUpperCase"
}
"""
        )

        self.assertEqual(entries[(0, 0)]["function_name"], "wrapper")
        self.assertEqual(entries[(0, 0)]["value"], "[run, 0]")
        self.assertEqual(entries[(1, 6)]["function_name"], "run")
        self.assertEqual(entries[(1, 6)]["value"], '"toUpperCase"')

    def test_infers_bytenode_placeholder_names_from_self_cache_constants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "sample"
            case_dir.mkdir()
            (case_dir / "sample.v8asm.dec.l4.js").write_text(
                """
function run(arg0) {
  // Constant pool:
  //   [6] = "toUpperCase"
}
""",
                encoding="utf-8",
            )
            (case_dir / "sample.bytenode.dec.l4.js").write_text(
                """
function run(arg0) {
  // Constant pool:
  //   [6] = "<undefined: segmentfault, might outside scope; object_chunk_offset=0xde48 tagged_chunk_offset=0xde49>"
}
""",
                encoding="utf-8",
            )

            hints = infer_placeholder_name_hints(case_dir, "sample")

        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["function_name"], "run")
        self.assertEqual(hints[0]["constant_index"], 6)
        self.assertEqual(hints[0]["object_chunk_offsets"], ["0xde48"])
        self.assertEqual(hints[0]["self_value"], '"toUpperCase"')

    def test_infers_placeholder_names_when_bytenode_has_extra_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            case_dir = Path(tmp) / "sample"
            case_dir.mkdir()
            (case_dir / "sample.v8asm.dec.l4.js").write_text(
                """
function wrapper() {
  // Constant pool:
  //   [0] = [allFeatures, 0]
}
function allFeatures() {
  // Constant pool:
  //   [10] = "JSON"
}
""",
                encoding="utf-8",
            )
            (case_dir / "sample.bytenode.dec.l4.js").write_text(
                """
function wrapper() {
  // Constant pool:
  //   [0] = String[11]: #allFeatures
}
function String_0() {
  // Constant pool:
  //   [0] = "extra"
}
function allFeatures() {
  // Constant pool:
  //   [10] = "<undefined: segmentfault, might outside scope; object_chunk_offset=0xee78 tagged_chunk_offset=0xee79>"
}
""",
                encoding="utf-8",
            )

            hints = infer_placeholder_name_hints(case_dir, "sample")

        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["function_name"], "allFeatures")
        self.assertEqual(hints[0]["constant_index"], 10)
        self.assertEqual(hints[0]["object_chunk_offsets"], ["0xee78"])
        self.assertEqual(hints[0]["self_value"], '"JSON"')

    def test_summarizes_placeholder_offsets(self) -> None:
        summary = summarize_placeholder_offsets(
            [
                {
                    "case": "05_object_calls",
                    "function_name": "greet",
                    "constant_index": 2,
                    "object_chunk_offsets": ["0xde48"],
                    "placeholder": "<undefined: segmentfault; object_chunk_offset=0xde48>",
                    "self_value": '"toUpperCase"',
                },
                {
                    "case": "09_all_features",
                    "function_name": "allFeatures",
                    "constant_index": 6,
                    "object_chunk_offsets": ["0xde48"],
                    "placeholder": "<undefined: segmentfault; object_chunk_offset=0xde48>",
                    "self_value": '"toUpperCase"',
                },
                {
                    "case": "20_rest_spread_calls",
                    "function_name": "run",
                    "constant_index": 2,
                    "object_chunk_offsets": ["0xd478"],
                    "placeholder": "<undefined: segmentfault; object_chunk_offset=0xd478>",
                    "self_value": '"collect"',
                },
            ],
            {
                "0xde48": {"inside+0x10@[0xde38,0xde50)"},
                "0xd478": {"inside+0x10@[0xd468,0xd480)"},
            },
        )

        self.assertEqual(
            summary,
            [
                {
                    "object_chunk_offset": "0xd478",
                    "self_values": ['"collect"'],
                    "cases": ["20_rest_spread_calls"],
                    "current_ro_objects": ["inside+0x10@[0xd468,0xd480)"],
                },
                {
                    "object_chunk_offset": "0xde48",
                    "self_values": ['"toUpperCase"'],
                    "cases": ["05_object_calls", "09_all_features"],
                    "current_ro_objects": ["inside+0x10@[0xde38,0xde50)"],
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
