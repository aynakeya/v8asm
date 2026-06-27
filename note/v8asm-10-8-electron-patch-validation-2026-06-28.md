# v8asm 10.8 Electron patch validation notes

This note records the follow-up after the 10.8 Electron cache exposed that
`v8asm-10.2.patch` is not a clean 3way patch for `10.8.168.25`.

## Root Cause

The first all-patch 3way apply check failed only for:

```bash
git apply --3way --recount v8patch/v8asm-10.2.patch
```

on V8 tag `10.8.168.25`. The conflicts were in:

- `src/objects/code.cc`
- `src/snapshot/code-serializer.cc`

`src/objects/code.cc` conflicted because V8 10.8 already contains the newer
handle-based `BytecodeArray::Disassemble` constant-pool and handler-table code
that the 10.2 patch has to add manually. Reapplying the 10.2 edit to 10.8 is
therefore wrong. The fix is a dedicated `v8patch/v8asm-10.8.patch` that keeps
the 10.8 native disassembly code and carries the same `v8asm`,
`--snapshot_blob`, cached-data sanity bypass, and forced startup snapshot
version mismatch bypass.

## Build

The 10.8 build used the official checkout flow and the fixed build parallelism:

```bash
cd /home/aynakeya/workspace/tmp/v8test
source start_env.md
cd v8
git checkout 10.8.168.25
gclient sync --with_branch_heads --with_tags
git apply --3way --recount /home/aynakeya/workspace/v8asm/v8patch/v8asm-10.8.patch
gn gen out/v8asm.10.8.electron.x64.release --args='is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_embedder_string="-electron.0"'
autoninja -j10 -C out/v8asm.10.8.electron.x64.release v8asm
```

The build completed all `1942/1942` ninja targets. The resulting binary reports:

```text
10.8.168.25-electron.0
is_debug=false
v8_enable_object_print=true
v8_enable_disassembler=true
v8_enable_pointer_compression=true
v8_enable_static_roots=false
```

The cache directory
`tests/decomp_rounds/bin_cache/v8asm.10.8.electron.x64.release/` was refreshed
from the V8 out directory, including the out-dir generated `snapshot_blob.bin`.

## Verification

10.8 self round with explicit sibling snapshot:

```bash
V8ASM=/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.10.8.electron.x64.release/v8asm
SNAP=/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.10.8.electron.x64.release/snapshot_blob.bin

$V8ASM --snapshot_blob "$SNAP" asm tests/decomp_rounds/cases/01_arith.js -o /tmp/v8asm-10.8-verify/01_arith.jsc
$V8ASM --snapshot_blob "$SNAP" checkversion /tmp/v8asm-10.8-verify/01_arith.jsc
$V8ASM --snapshot_blob "$SNAP" disasm /tmp/v8asm-10.8-verify/01_arith.jsc
python3 decompiler/v8decompiler.py /tmp/v8asm-10.8-verify/01_arith.disasm.txt --level 4 --runtime
```

Observed result:

- strict `checkversion` found `10.8.168.25`
- `disasm.err`: 0 lines
- `decompile.err`: 0 lines
- disassembly lines: 89
- decompiled lines: 61

All patch files were then checked with real temporary V8 worktrees using
`git apply --3way --recount`. The applied `src/disassembler/main.cc` line count
was checked against each patch hunk header:

| patch | tag | main.cc lines |
|---|---:|---:|
| `v8asm-10.2.patch` | `10.2.154.26` | 938 |
| `v8asm-10.8.patch` | `10.8.168.25` | 938 |
| `v8asm-11.3.patch` | `11.3.244.8` | 938 |
| `v8asm-11.4.patch` | `11.4.183.14` | 938 |
| `v8asm-11.9.patch` | `11.9.169.7` | 937 |
| `v8asm-12.4.patch` | `12.4.254.21` | 928 |
| `v8asm-12.9.patch` | `12.9.202.28` | 927 |
| `v8asm-13.2.patch` | `13.2.152.41` | 913 |
| `v8asm-13.4.patch` | `13.4.114.21` | 913 |
| `v8asm.patch` | `13.6.233.10` | 999 |

Repository verification commands:

```bash
python3 tests/decomp_rounds/check_patch_text.py
python3 tests/decomp_rounds/check_bin_cache.py
python3 tests/decomp_rounds/audit_patch_coverage.py --strict
python3 -m unittest discover -s tests -p 'test*.py'
python3 tests/decomp_rounds/check_electron_snapshot_round.py
./tests/decomp_rounds/run_version_matrix.sh
```

Observed result:

- `check_patch_text.py`: every patch and `v8patch/main.cc` reported `ok`
- `check_bin_cache.py`: `bin_cache_ok=1`; the refreshed 10.8 cache matched the
  visible V8 out `snapshot_blob.bin`
- `audit_patch_coverage.py --strict`: `coverage_gaps=0`
- unit tests: 129 tests, `OK`
- Electron snapshot round: both `snapshot_blob` and `v8_context_snapshot`
  passed `checkversion`, `disasm`, and decompile
- version matrix: warnings 0, failures 0; 10.8 self-cache row passed with
  `raw:0 unknown:0 undef:0`

## Static Roots

The 10.8 Electron-style build reports `v8_enable_static_roots=false`. Static
roots or fixed-offset mismatches are still treated as build-flag mismatches,
not cached-data header mismatches. The rule remains: build a matching
`v8_enable_static_roots=true` or `false` variant as a best-effort probe, and do
not patch around V8's read-only snapshot layout checks.
