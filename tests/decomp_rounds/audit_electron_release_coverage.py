#!/usr/bin/env python3
"""Audit official Electron runtime coverage for built Electron v8asm rows."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METADATA = Path("/tmp/electron-releases.json")
DEFAULT_METADATA_URL = "https://releases.electronjs.org/releases.json"
DEFAULT_ELECTRON_CACHE = Path("/home/aynakeya/workspace/tmp/v8test/electron-cache")
DEFAULT_BUILD_SUMMARY = ROOT / "tests/decomp_rounds/build_matrix/summary.md"
DEFAULT_ELECTRON_SUMMARY = ROOT / "tests/decomp_rounds/electron_matrix/summary.md"
DEFAULT_OUT = ROOT / "tests/decomp_rounds/electron_release_coverage/summary.md"


@dataclass(frozen=True)
class BuildRow:
    label: str
    version: str
    out: str
    status: str

    @property
    def numeric_v8(self) -> str:
        return self.version.removesuffix("-electron.0")


@dataclass(frozen=True)
class ElectronRow:
    electron_dir: str
    electron_version: str
    electron_v8: str
    v8asm: str
    snapshot: str
    checkversion: str
    disasm: str
    decompile: str
    quality: str
    crash: str


def strip_ticks(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def markdown_cells(line: str) -> list[str]:
    return [strip_ticks(cell) for cell in line.strip().strip("|").split("|")]


def load_build_rows(path: Path) -> list[BuildRow]:
    rows: list[BuildRow] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("| `"):
            continue
        cells = markdown_cells(line)
        if len(cells) < 7:
            continue
        label, _tag, _patch, out, status, version, _args = cells[:7]
        if "electron" not in label or "nostaticroots" in label:
            continue
        rows.append(BuildRow(label=label, version=version, out=out, status=status))
    return rows


def load_electron_rows(path: Path) -> list[ElectronRow]:
    if not path.exists():
        return []
    rows: list[ElectronRow] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("| `"):
            continue
        cells = markdown_cells(line)
        if len(cells) < 12:
            continue
        rows.append(
            ElectronRow(
                electron_dir=cells[0],
                electron_version=cells[1],
                electron_v8=cells[2],
                v8asm=cells[3],
                snapshot=cells[6],
                checkversion=cells[7],
                disasm=cells[8],
                decompile=cells[9],
                quality=cells[10],
                crash=cells[11],
            )
        )
    return rows


def load_metadata(path: Path, url: str, refresh: bool) -> list[dict]:
    if refresh or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url) as response:
            path.write_bytes(response.read())
    return json.loads(path.read_text(encoding="utf-8"))


def stable_linux_releases(metadata: list[dict]) -> dict[str, list[dict]]:
    by_v8: dict[str, list[dict]] = {}
    for item in metadata:
        version = str(item.get("version", ""))
        if any(tag in version for tag in ("nightly", "alpha", "beta")):
            continue
        if "linux-x64" not in (item.get("files") or []):
            continue
        by_v8.setdefault(str(item.get("v8", "")), []).append(item)
    return by_v8


def cached_release(cache: Path, version: str) -> bool:
    release_dir = cache / f"v{version}-linux-x64"
    return (
        (release_dir / "electron").is_file()
        and (release_dir / "snapshot_blob.bin").is_file()
        and (release_dir / "v8_context_snapshot.bin").is_file()
    )


def matrix_ok(rows: list[ElectronRow], electron_v8: str, v8asm_name: str) -> bool:
    matched = [
        row
        for row in rows
        if row.electron_v8 == f"{electron_v8}-electron.0"
        and row.v8asm == v8asm_name
        and row.checkversion == "ok"
        and row.disasm == "ok"
        and row.decompile == "ok"
        and row.crash == "no"
        and re.search(r"raw:0\s+unknown:0\s+undef:0", row.quality)
    ]
    snapshots = {row.snapshot for row in matched}
    return {"snapshot_blob", "v8_context_snapshot"}.issubset(snapshots)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--metadata-url", default=DEFAULT_METADATA_URL)
    parser.add_argument("--refresh-metadata", action="store_true")
    parser.add_argument("--electron-cache", type=Path, default=DEFAULT_ELECTRON_CACHE)
    parser.add_argument("--build-summary", type=Path, default=DEFAULT_BUILD_SUMMARY)
    parser.add_argument("--electron-summary", type=Path, default=DEFAULT_ELECTRON_SUMMARY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--strict-official", action="store_true")
    args = parser.parse_args()

    metadata = load_metadata(args.metadata, args.metadata_url, args.refresh_metadata)
    releases_by_v8 = stable_linux_releases(metadata)
    build_rows = load_build_rows(args.build_summary)
    electron_rows = load_electron_rows(args.electron_summary)

    failures: list[str] = []
    warnings: list[str] = []
    lines: list[str] = []
    for row in build_rows:
        releases = releases_by_v8.get(row.numeric_v8, [])
        release_versions = [str(item["version"]) for item in releases]
        cached = [version for version in release_versions if cached_release(args.electron_cache, version)]
        v8asm_name = Path(row.out).name
        runtime_ok = matrix_ok(electron_rows, row.numeric_v8, v8asm_name)

        if not releases:
            status = "no-official-exact"
            warnings.append(f"{row.label}: no stable linux-x64 Electron release for V8 {row.numeric_v8}")
            if args.strict_official:
                failures.append(warnings[-1])
        elif not cached:
            status = "release-not-cached"
            failures.append(
                f"{row.label}: official release exists for V8 {row.numeric_v8} but is not cached"
            )
        elif not runtime_ok:
            status = "matrix-missing"
            failures.append(
                f"{row.label}: cached official release exists but Electron matrix did not pass both snapshots"
            )
        else:
            status = "runtime-ok"

        lines.append(
            "| "
            + " | ".join(
                (
                    row.label,
                    row.version,
                    v8asm_name,
                    ", ".join(release_versions[:5]) if release_versions else "-",
                    ", ".join(cached) if cached else "-",
                    status,
                )
            )
            + " |"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        f.write("# Electron Release Coverage Audit\n\n")
        f.write(f"- metadata: `{args.metadata}`\n")
        f.write(f"- electron_cache: `{args.electron_cache}`\n")
        f.write(f"- build_summary: `{args.build_summary}`\n")
        f.write(f"- electron_summary: `{args.electron_summary}`\n\n")
        f.write("| build label | v8asm version | v8asm cache | official stable linux-x64 releases | cached releases | status |\n")
        f.write("|---|---:|---|---|---|---|\n")
        for line in lines:
            f.write(line + "\n")
        f.write("\n## Gate Summary\n\n")
        f.write(f"- warnings: {len(warnings)}\n")
        for warning in warnings:
            f.write(f"  - {warning}\n")
        f.write(f"- failures: {len(failures)}\n")
        for failure in failures:
            f.write(f"  - {failure}\n")

    print(f"Done. Summary: {args.out}")
    if failures:
        print("electron_release_coverage_failures:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("electron_release_coverage_ok=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
