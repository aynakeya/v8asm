# v8asm static-roots and full build matrix validation

Date: 2026-06-28

## Build matrix

The full source build matrix was rebuilt from
`/home/aynakeya/workspace/tmp/v8test/v8` using the official depot_tools
workflow:

```bash
gclient sync --with_branch_heads --with_tags
autoninja -j10 -C <out> v8asm
```

The build preserved existing `out/` caches. It did not use `gclient sync -D`.

Fresh result:

```text
Build matrix report: /home/aynakeya/workspace/v8asm/tests/decomp_rounds/build_matrix/summary.md
build_matrix_ok=1
```

The matrix produced 21 successful rows:

```text
10.2-node, 10.2-electron
10.8-node, 10.8-electron
11.3-node, 11.3-electron
11.4-node, 11.4-electron
11.9-node, 11.9-electron
12.4-node, 12.4-electron
12.9-node, 12.9-electron
13.2-node, 13.2-electron, 13.2-electron-nostaticroots
13.4-node, 13.4-electron-staticroots
13.6-node, 13.6-electron
```

Electron-oriented rows that need static roots were compiled with:

```text
v8_enable_pointer_compression=true
v8_enable_static_roots=true
```

The explicit no-static-roots 13.2 Electron probe was also rebuilt:

```text
v8asm.13.2.152.41.electron.nostaticroots.x64.release
v8_enable_pointer_compression=true
v8_enable_static_roots=false
```

This probe is intentionally not the normal Electron 34.3.0 path. It is kept as
a diagnostic build for snapshots that fail in the opposite static-roots
direction.

## Bin cache rule

`tests/decomp_rounds/bin_cache/*/snapshot_blob.bin` must be the V8 build output
snapshot from the corresponding `out/` directory, not an Electron or
application context snapshot.

Fresh checks:

```text
find tests/decomp_rounds/bin_cache -name v8_context_snapshot.bin -print
```

returned no files.

```text
python3 tests/decomp_rounds/check_bin_cache.py
checked_dirs=23
bin_cache_ok=1
```

The rebuilt 13.2, 13.4, and 13.6 caches matched visible V8 `out/`
`snapshot_blob.bin` files by hash.

## Static-roots focused validation

Local Electron coverage currently available:

```text
electron dir: /home/aynakeya/workspace/tmp/v8test/electron-cache/v34.3.0-linux-x64
Electron: 34.3.0
V8: 13.2.152.41-electron.0
```

The matching v8asm is:

```text
tests/decomp_rounds/bin_cache/v8asm.13.2.152.41.electron.x64.release/v8asm
version: 13.2.152.41-electron.0
v8_enable_pointer_compression=true
v8_enable_static_roots=true
```

Focused command:

```bash
tests/decomp_rounds/bin_cache/v8asm.13.2.152.41.electron.x64.release/v8asm \
  disasm tests/decomp_rounds/electron_matrix/v34.3.0-linux-x64/electron-case.jsc \
  --snapshot_blob /home/aynakeya/workspace/tmp/v8test/electron-cache/v34.3.0-linux-x64/v8_context_snapshot.bin \
  --force-incompatible
```

Result:

```text
exit=0
output includes BytecodeArray records and SharedFunctionInfo records
no Fatal error
no Check failed
```

The mismatched no-static-roots probe used the same `.jsc` and same
`v8_context_snapshot.bin`:

```bash
tests/decomp_rounds/bin_cache/v8asm.13.2.152.41.electron.nostaticroots.x64.release/v8asm \
  disasm tests/decomp_rounds/electron_matrix/v34.3.0-linux-x64/electron-case.jsc \
  --snapshot_blob /home/aynakeya/workspace/tmp/v8test/electron-cache/v34.3.0-linux-x64/v8_context_snapshot.bin \
  --force-incompatible
```

Result:

```text
exit=133
Fatal error in , line 0
Check failed: false == fixed_offset.
```

Conclusion: `fixed_offset` is a startup snapshot object-layout/static-roots
compatibility failure. The correct handling is to compile and select the
matching `v8_enable_static_roots` variant. Do not bypass this check in V8 object
layout code.

## Runtime verification

Fresh commands:

```bash
python3 tests/decomp_rounds/check_patch_text.py
python3 tests/decomp_rounds/check_bin_cache.py
python3 tests/decomp_rounds/audit_patch_coverage.py --strict
python3 -m unittest discover -s tests -p 'test*.py'
python3 tests/decomp_rounds/check_electron_snapshot_round.py
python3 tests/decomp_rounds/check_electron_version_matrix.py
./tests/decomp_rounds/run_version_matrix.sh
git diff --check
git -C /home/aynakeya/workspace/tmp/v8test/v8 status --short --untracked-files=no
```

Fresh results:

```text
check_patch_text.py: all v8patch/*.patch and v8patch/main.cc ok
check_bin_cache.py: bin_cache_ok=1
audit_patch_coverage.py --strict: coverage_gaps=0
unittest: Ran 129 tests, OK
check_electron_snapshot_round.py:
  snapshot_blob: checkversion=0 disasm=0 decompile=0
  v8_context_snapshot: checkversion=0 disasm=0 decompile=0
  electron_snapshot_round_ok=1
check_electron_version_matrix.py: electron_version_matrix_ok=1
run_version_matrix.sh: warnings=0 failures=0
git diff --check: no output
V8 tracked status: no output
```

The Electron version matrix currently covers only the local Electron release in
`electron-cache`, which is Electron 34.3.0 / V8
`13.2.152.41-electron.0`. Other Electron major-version rows are compiled and
covered by self-generated cached-data tests, but need matching local Electron
packages/snapshots for external Electron `.jsc` runtime validation.

## Why 13.4 needed the special external-reference patch

Cached-data/header bypasses handle the `.jsc` payload:

```text
magic
version_hash
flags_hash
read_only_snapshot_checksum
payload_length
checksum
```

Snapshot version bypass only lets V8 try a startup snapshot whose version string
has a different suffix, for example `13.4.114.21-electron.0` versus
`13.4.114.21`.

The 13.4 Atom/Electron failure happened earlier, while V8 was initializing the
startup snapshot. Electron's startup snapshot can contain an external-reference
table whose alias count/sentinel differs from vanilla V8. That failure happens
before v8asm can deserialize the `.jsc` cached data.

So 13.4 needed a startup-deserializer compatibility patch that accepts the
Electron external-reference table shape in forced mode. It is separate from the
cached-data header bypass and from the snapshot version suffix bypass.

## Operational rule

For Electron/application snapshots:

1. Choose the v8asm binary whose `v8asm version` matches the embedder V8 string.
2. Match pointer compression and static roots with the snapshot.
3. Pass application snapshots explicitly with `--snapshot_blob`.
4. Keep `bin_cache/snapshot_blob.bin` as the V8 build output snapshot.
5. Patch only cached-data header/sanity/version checks for forced recovery.
   Treat static-roots/object-layout failures as a build-flag mismatch unless a
   narrower startup snapshot compatibility issue is proven.
