"""Regenerate selected semantic caches with a manifest-pinned, installed Node."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/semantic_fixtures"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", nargs="*", help="Fixture names without extensions")
    parser.add_argument("--all", action="store_true", help="All fixtures configured for this runtime")
    parser.add_argument("--node", default="node", help="Installed Node executable; never downloads or builds")
    args = parser.parse_args()
    if bool(args.fixtures) == args.all:
        parser.error("specify fixture names or --all")
    if os.environ.get("NODE_OPTIONS"):
        parser.error("unset NODE_OPTIONS so cache generation uses only the recorded flags")
    manifest_path = FIXTURES / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    versions = json.loads(subprocess.check_output(
        [args.node, "-p", "JSON.stringify({node:process.versions.node,v8:process.versions.v8,"
         "electron:process.versions.electron,arch:process.arch,platform:process.platform})"],
        text=True, timeout=10,
    ))
    matched = next(((name, runtime) for name, runtime in manifest["runtimes"].items()
                    if runtime["node_version"] == versions["node"]
                    and runtime["v8_version"] == versions["v8"]
                    and not versions.get("electron")), None)
    if matched is None:
        parser.error(f"runtime not in manifest: {versions}")
    runtime_name, runtime = matched
    available = {path.stem for path in FIXTURES.glob("*.js")}
    configured = available if runtime["fixtures"] == ["*"] else set(runtime["fixtures"])
    names = sorted(configured) if args.all else args.fixtures
    for name in names:
        if name not in available or name not in configured:
            parser.error(f"fixture {name!r} is not configured for {runtime_name}")

    for name in names:
        source = FIXTURES / f"{name}.js"
        cache = FIXTURES / f"{name}{runtime['cache_suffix']}.jsc"
        subprocess.run(
            [args.node, *manifest["compile_flags"], "tests/fixtures/generate_cached_data.cjs",
             str(source.relative_to(ROOT)), str(cache.relative_to(ROOT))],
            cwd=ROOT, check=True, timeout=30,
        )
        manifest["artifacts"][cache.name] = {
            "runtime": runtime_name,
            "node_version": versions["node"], "v8_version": versions["v8"],
            "arch": versions["arch"], "platform": versions["platform"],
            "compile_flags": manifest["compile_flags"],
            "source": source.name,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "cache_sha256": hashlib.sha256(cache.read_bytes()).hexdigest(),
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(f"{cache.name}: Node {versions['node']}, V8 {versions['v8']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
