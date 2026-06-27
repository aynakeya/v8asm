#!/usr/bin/env python3
"""Audit patch-to-binary coverage for the v8asm version matrix.

This is intentionally a reporting tool. It does not prove a patch can compile
on a clean checkout; it shows which patch families currently have cached node
and Electron-style binaries, and which visible V8 out directories are only GN
directories without a built v8asm binary.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BIN_CACHE = ROOT / "tests" / "decomp_rounds" / "bin_cache"
DEFAULT_V8_OUT = Path("/home/aynakeya/workspace/tmp/v8test/v8/out")
DEFAULT_PATCH_DIR = ROOT / "v8patch"


@dataclass(frozen=True)
class PatchFamily:
    patch: str
    family: str
    description: str
    require_node: bool = True
    require_electron: bool = True


PATCH_FAMILIES = (
    PatchFamily("v8asm-10.2.patch", "10.2", "V8 10.2 / Node 18 line"),
    PatchFamily(
        "v8asm-10.8.patch",
        "10.8",
        "V8 10.8 / Electron line",
        require_node=False,
    ),
    PatchFamily("v8asm-11.3.patch", "11.3", "V8 11.3 / Node 20 line"),
    PatchFamily("v8asm-11.4.patch", "11.4", "V8 11.4 / Electron line"),
    PatchFamily("v8asm-11.9.patch", "11.9", "V8 11.9 research line"),
    PatchFamily("v8asm-12.4.patch", "12.4", "V8 12.4 / Node 22 line"),
    PatchFamily("v8asm-12.9.patch", "12.9", "V8 12.9 research line"),
    PatchFamily("v8asm-13.2.patch", "13.2", "V8 13.2 / Electron 34 line"),
    PatchFamily("v8asm-13.4.patch", "13.4", "V8 13.4 / Atom Electron line"),
    PatchFamily("v8asm.patch", "13.6", "current 13.6 line"),
)


@dataclass(frozen=True)
class CacheEntry:
    name: str
    version: str
    build_args: tuple[str, ...]
    has_v8asm: bool
    has_snapshot: bool

    @property
    def mode(self) -> str:
        if "electron" in self.name or "-electron." in self.version:
            return "electron"
        return "node"


@dataclass(frozen=True)
class OutEntry:
    name: str
    has_v8asm: bool
    has_snapshot: bool
    args: tuple[str, ...]


def read_text_lines(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    return tuple(path.read_text(encoding="utf-8", errors="replace").splitlines())


def load_cache_entries(bin_cache: Path) -> list[CacheEntry]:
    entries: list[CacheEntry] = []
    if not bin_cache.exists():
        return entries
    for cache_dir in sorted(p for p in bin_cache.iterdir() if p.is_dir()):
        version_lines = read_text_lines(cache_dir / "version.txt")
        entries.append(
            CacheEntry(
                name=cache_dir.name,
                version=version_lines[0] if version_lines else "",
                build_args=read_text_lines(cache_dir / "build-args.txt"),
                has_v8asm=(cache_dir / "v8asm").is_file(),
                has_snapshot=(cache_dir / "snapshot_blob.bin").is_file(),
            )
        )
    return entries


def load_out_entries(v8_out: Path) -> list[OutEntry]:
    entries: list[OutEntry] = []
    if not v8_out.exists():
        return entries
    for out_dir in sorted(p for p in v8_out.iterdir() if p.is_dir() and p.name.startswith("v8asm.")):
        entries.append(
            OutEntry(
                name=out_dir.name,
                has_v8asm=(out_dir / "v8asm").is_file(),
                has_snapshot=(out_dir / "snapshot_blob.bin").is_file(),
                args=read_text_lines(out_dir / "args.gn"),
            )
        )
    return entries


def belongs_to_family(name: str, version: str, family: str) -> bool:
    needle = f"v8asm.{family}."
    return name.startswith(needle) or version.startswith(family)


def format_names(names: list[str]) -> str:
    return ", ".join(names) if names else "-"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin-cache", type=Path, default=DEFAULT_BIN_CACHE)
    parser.add_argument("--v8-out", type=Path, default=DEFAULT_V8_OUT)
    parser.add_argument("--patch-dir", type=Path, default=DEFAULT_PATCH_DIR)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    caches = load_cache_entries(args.bin_cache)
    outs = load_out_entries(args.v8_out)
    problems: list[str] = []

    print("# Patch Coverage Audit")
    print(f"bin_cache={args.bin_cache}")
    print(f"v8_out={args.v8_out}")
    print()
    print("| patch | family | patch | node cache | electron cache | built out | out without v8asm | gaps |")
    print("|---|---:|---:|---|---|---|---|---|")
    for family in PATCH_FAMILIES:
        patch_exists = (args.patch_dir / family.patch).is_file()
        family_caches = [
            c for c in caches if belongs_to_family(c.name, c.version, family.family)
        ]
        node_caches = [
            c.name for c in family_caches if c.mode == "node" and c.has_v8asm and c.has_snapshot
        ]
        electron_caches = [
            c.name
            for c in family_caches
            if c.mode == "electron" and c.has_v8asm and c.has_snapshot
        ]
        family_outs = [o for o in outs if o.name.startswith(f"v8asm.{family.family}.")]
        built_outs = [o.name for o in family_outs if o.has_v8asm and o.has_snapshot]
        incomplete_outs = [o.name for o in family_outs if not (o.has_v8asm and o.has_snapshot)]
        gaps: list[str] = []
        if not patch_exists:
            gaps.append("missing patch")
        if family.require_node and not node_caches:
            gaps.append("missing node cache")
        if family.require_electron and not electron_caches:
            gaps.append("missing electron cache")
        if gaps:
            problems.append(f"{family.patch}: {', '.join(gaps)}")
        print(
            "| "
            + " | ".join(
                (
                    family.patch,
                    family.family,
                    "yes" if patch_exists else "no",
                    format_names(node_caches),
                    format_names(electron_caches),
                    format_names(built_outs),
                    format_names(incomplete_outs),
                    ", ".join(gaps) if gaps else "none",
                )
            )
            + " |"
        )

    print()
    if problems:
        print("GAPS")
        for problem in problems:
            print(f"- {problem}")
    else:
        print("coverage_gaps=0")

    if args.strict and problems:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
