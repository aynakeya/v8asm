from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

from checkversion import (
    Version,
    calculate_version_hash,
    find_version,
    parse_cached_data_hash,
)
from disassembler.profiles import load_profiles


ROOT = Path(__file__).resolve().parents[1]


class CheckVersionTests(unittest.TestCase):
    def test_hashes_match_generated_profiles(self) -> None:
        for profile in load_profiles().profiles:
            with self.subTest(version=profile.version):
                parts = map(int, profile.version.split("."))
                self.assertEqual(
                    calculate_version_hash(*parts), profile.version_hash
                )

    def test_reads_little_endian_hash_from_cached_data(self) -> None:
        self.assertEqual(
            parse_cached_data_hash(ROOT / "samples" / "main.d8.jsc"),
            0x2B2C7714,
        )

    def test_parallel_search_finds_modern_version(self) -> None:
        target = calculate_version_hash(13, 6, 233, 10)
        self.assertEqual(
            find_version(
                target,
                major_range=(13, 14),
                minor_range=(5, 7),
                build_range=(230, 240),
                patch_range=(0, 20),
                jobs=2,
            ),
            Version(13, 6, 233, 10),
        )

    def test_parallel_search_finds_legacy_version(self) -> None:
        target = calculate_version_hash(10, 2, 154, 4)
        self.assertEqual(
            find_version(
                target,
                major_range=(10, 11),
                minor_range=(2, 3),
                build_range=(150, 160),
                patch_range=(0, 10),
                jobs=2,
            ),
            Version(10, 2, 154, 4),
        )

    def test_module_cli_calculates_hash(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "checkversion",
                "--calculate",
                "13.4.114.21",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        self.assertEqual(
            result.stdout,
            "version: 13.4.114.21\nversion_hash: 0x2135fe8d\n",
        )


if __name__ == "__main__":
    unittest.main()
