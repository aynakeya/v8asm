# Electron Atom JSC recovery notes for V8 13.4

Date: 2026-06-14

Target sample: `atom.compiled.dist.jsc`

## Summary

`atom.compiled.dist.jsc` is raw V8 cached data from an Electron build. The version hash resolves to V8 `13.4.114.21`, so the V8 checkout was moved to the official `13.4.114.21` tag and synchronized with `gclient sync --with_branch_heads --with_tags` using the local `start_env.md` depot_tools/proxy setup.

The plain V8 13.4 build does not exactly match Electron cached data. `checkversion` reports the same V8 version hash, but different cached-data `magic`, `flags_hash`, and read-only snapshot checksum. Strict deserialization correctly refuses the file. Forced deserialization originally aborted before printing anything because the deserializer indexed the current build read-only heap pages with an Electron snapshot page index.

The important fix is in V8, not in the Python decompiler and not in object-printer protection: `Deserializer::ReadReadOnlyHeapRef` now validates the read-only page index and page offset before touching `read_only_space->pages()[chunk_index]`. Invalid read-only heap references are replaced with `undefined` and reported on stderr. This makes forced Electron recovery produce a partial but useful disassembly instead of aborting.

After the matching files were added under `v8context/`, the correct startup blob for this `.jsc` turned out to be `v8context/v8_context_snapshot.bin`, not `v8context/snapshot_blob.bin`. Its header contains read-only snapshot checksum `0x4e6b3214`, exactly matching `atom.compiled.dist.jsc`.

`v8_context_snapshot.bin` still needs an Electron-flavored V8 build (`v8_embedder_string="-electron.0"`). Its serialized external reference table has size `1671`, while the vanilla V8 `13.4.114.21` build has size `1672`; in startup deserialization that means the Electron sentinel is `1592` and the current binary sentinel is `1593`. A research-only environment switch, `V8ASM_ALLOW_SNAPSHOT_EXTERNAL_REFERENCE_MISMATCH=1`, lets v8asm infer the snapshot sentinel from the snapshot magic and continue. With the correct context snapshot, the `ReadReadOnlyHeapRef` fallback is no longer used.

## Evidence

13.4 build used for the sample:

```text
/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.13.4.x64.release/v8asm version
13.4.114.21

/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.13.4.x64.release/v8asm build-args
is_debug=false
v8_enable_object_print=true
v8_enable_disassembler=true
v8_enable_pointer_compression=true
```

Header check against `atom.compiled.dist.jsc`:

```text
Version hash: hex = 8dfe3521 , uint32 = 0x2135fe8d (557186701)
Cached data header:
  magic: 0xc0de0687 (expected 0xc0de0688) mismatch
  version_hash: 0x2135fe8d (expected 0x2135fe8d)
  source_hash: 0x000394f6 (informational)
  flags_hash: 0x59eeb3ef (expected 0x3c779525) mismatch
  read_only_snapshot_checksum: 0x4e6b3214 (expected 0x5595c506) mismatch
  payload_length: 378832 (max 378832)
  checksum: 0x00000000
Found matching version: 13.4.114.21
```

Header check with `v8context/v8_context_snapshot.bin` and the Electron-suffix build:

```text
v8asm: using snapshot external reference table size 1671 (current 1672), inferred startup sentinel 1592 (current 1593)
Cached data header:
  magic: 0xc0de0687 (expected 0xc0de0688) mismatch
  version_hash: 0x2135fe8d (expected 0x2135fe8d)
  source_hash: 0x000394f6 (informational)
  flags_hash: 0x59eeb3ef (expected 0x3c779525) mismatch
  read_only_snapshot_checksum: 0x4e6b3214 (expected 0x4e6b3214)
  payload_length: 378832 (max 378832)
  checksum: 0x00000000
Found matching version: 13.4.114.21
```

Strict mode result:

```text
Refusing to deserialize incompatible cached data. Use --force-incompatible for best-effort recovery.
```

Original forced crash before the fix:

```text
../../third_party/libc++/src/include/__vector/vector.h:399: assertion __n < size() failed: vector[] index out of bounds
#6  Deserializer<Isolate>::ReadReadOnlyHeapRef(...)
#7  Deserializer<Isolate>::ReadObject(...)
#52 ObjectDeserializer::Deserialize()
#54 CodeSerializer::Deserialize(...)
#55 do_disasm(...)
```

After the fix, forced disassembly succeeds:

```text
/tmp/atom.13.4.force.patched.disasm.txt   112389 lines, 6477509 bytes
/tmp/atom.13.4.force.patched.disasm.err      171 lines,   11066 bytes
```

The stderr diagnostics show the remaining Electron read-only snapshot mismatch explicitly:

```text
v8asm: invalid ReadOnlyHeapRef [2, 35976], substituting undefined
v8asm: invalid ReadOnlyHeapRef [2, 32336], substituting undefined
...
```

After using `v8_context_snapshot.bin`, the forced disassembly no longer reports invalid read-only heap references:

```text
/tmp/atom.13.4.v8context.force.disasm.txt   112391 lines, 6452189 bytes
/tmp/atom.13.4.v8context.force.disasm.err        9 lines,     400 bytes
```

The Python decompiler now handles this output and produces level-4 pseudo JS with runtime helpers:

```text
/tmp/atom.13.4.v8context.force.dec.l4.js       36038 lines, 1187504 bytes
/tmp/atom.13.4.v8context.force.decompile.err       0 bytes
```

## Code changes from this pass

- Added `v8patch/v8asm-13.4.patch` for the V8 `13.4.114.21` tag.
- Added a v8asm-global `--snapshot_blob <file>` option so the matching Electron
  snapshot can be passed directly instead of using an executable-side symlink.
- Patched V8's `SerializedCodeData::SanityCheck*` path for research forced
  recovery. When `v8asm` has already accepted `--force-incompatible`, V8 no
  longer rejects the cached data a second time because the cached-data `magic`
  or flags hash differs.
- Added read-only heap reference bounds checks in `src/snapshot/deserializer.cc` for forced recovery.
- Added `V8ASM_ALLOW_SNAPSHOT_EXTERNAL_REFERENCE_MISMATCH=1` as a research-only
  startup snapshot compatibility switch for Electron external-reference table
  size drift.
- Kept the diagnostic visible on stderr so partial recovery is not mistaken for native compatibility.
- Updated Python decompiler input reading to use UTF-8 replacement mode. V8 object printing can emit non-UTF-8 bytes for corrupted or embedder-specific string data.
- Updated `V8String.parse()` to parse both `#value` and quoted string payloads such as `[String]: "...\x0a..."`; only missing payloads fall back to an address-derived placeholder.
- Added tests for non-UTF-8 disassembly input, missing string value fallback, and quoted V8 string payloads.

Validation run:

```text
python3 -m unittest discover -s tests -p test_*.py
Ran 85 tests in 0.016s
OK
```

Patch usability check:

```text
git worktree add --detach /tmp/v8-patchcheck-13.4 13.4.114.21
git -C /tmp/v8-patchcheck-13.4 apply --check --3way /home/aynakeya/workspace/v8asm/v8patch/v8asm-13.4.patch
```

The patch applied cleanly to a fresh `13.4.114.21` worktree. The temporary worktree was removed afterwards. Existing V8 build output caches were not deleted.

Direct forced-load validation after adding the internal sanity-check bypass and
global `--snapshot_blob` to the patch template:

```text
out/v8asm.13.4.electron.x64.release/v8asm version
13.4.114.21-electron.0

out/v8asm.13.4.electron.x64.release/v8asm build-args
is_debug=false
v8_enable_object_print=true
v8_enable_disassembler=true
v8_enable_pointer_compression=true

self-cache smoke:
  /tmp/v8asm-13.4-electron-smoke.jsc         440 bytes
  disasm                                     3804 bytes
  decompiler                                 2174 bytes

Atom Electron forced load:
  /tmp/atom.13.4.electron.direct.disasm.txt  112391 lines, 6452189 bytes
  /tmp/atom.13.4.electron.direct.disasm.err       9 lines,     400 bytes
  /tmp/atom.13.4.electron.direct.dec.js       36038 lines, 1187504 bytes
```

The direct forced-load command still reports the expected Electron/vanilla
header differences, but it reaches the deserializer and prints bytecode:

```text
v8asm: using snapshot external reference table size 1671 (current 1672), inferred startup sentinel 1592 (current 1593)
Cached data header:
  magic: 0xc0de0687 (expected 0xc0de0688) mismatch
  version_hash: 0x2135fe8d (expected 0x2135fe8d)
  flags_hash: 0x59eeb3ef (expected 0x3c779525) mismatch
  read_only_snapshot_checksum: 0x4e6b3214 (expected 0x4e6b3214)
Forcing incompatible cached data; output may be partial.
```

## Cross-version patch sync

The Electron recovery fixes from `v8patch/v8asm-13.4.patch` were audited
against the other maintained major-version patches. Each V8 checkout was moved
to the target tag and synchronized with the official `gclient sync
--with_branch_heads --with_tags` flow before applying or refreshing the patch.
Existing `out/*` build caches were kept.

| patch | V8 tag used | synced Electron fixes | build/test status |
| --- | --- | --- | --- |
| `v8patch/v8asm.patch` | `13.6.233.10` | `--snapshot_blob`, cached-data sanity bypass, invalid `ReadOnlyHeapRef` fallback, startup external-reference mismatch opt-in | `autoninja -j10 -C out/x64.release v8asm`; asm/checkversion/disasm/decompiler smoke passed |
| `v8patch/v8asm-13.4.patch` | `13.4.114.21` | `--snapshot_blob`, cached-data sanity bypass, invalid `ReadOnlyHeapRef` fallback, startup external-reference mismatch opt-in | `autoninja -j10 -C out/v8asm.13.4.electron.x64.release v8asm`; self-cache smoke and `atom.compiled.dist.jsc` forced disasm/decompiler passed |
| `v8patch/v8asm-12.9.patch` | `12.9.109` | `--snapshot_blob`, cached-data sanity bypass, invalid `ReadOnlyHeapRef` fallback, startup external-reference mismatch opt-in | `autoninja -j10 -C out/v8asm.12.9.x64.release v8asm`; asm/checkversion/disasm/decompiler smoke passed |
| `v8patch/v8asm-12.4.patch` | `12.4.254.21` | `--snapshot_blob`, cached-data sanity bypass, invalid `ReadOnlyHeapRef` fallback | normal and Node22-like no-pointer-compression builds passed; asm/checkversion/disasm/decompiler smoke passed |
| `v8patch/v8asm-11.9.patch` | `11.9.172` | `--snapshot_blob`, cached-data sanity bypass, invalid `ReadOnlyHeapRef` fallback | final patch re-applied from clean source, rebuilt, and asm/checkversion/disasm/decompiler smoke passed |
| `v8patch/v8asm-11.3.patch` | `11.3.244.8` | `--snapshot_blob`, cached-data sanity bypass, invalid `ReadOnlyHeapRef` fallback adapted to the 11.3 `Object` API | `autoninja -j10 -C out/v8asm.11.3.node20.x64.release v8asm`; self-cache smoke and Node20/bytenode forced disasm/decompiler passed |
| `v8patch/v8asm-10.2.patch` | `10.2.154.26` | `--snapshot_blob`, cached-data sanity bypass, invalid `ReadOnlyHeapRef` fallback adapted to the 10.2 cached-data header | `autoninja -j10 -C out/v8asm.10.2.node18.x64.release v8asm`; self-cache smoke and Node18/bytenode forced disasm/decompiler passed |

The startup external-reference-table mismatch switch is not present in the 12.4
and 11.9 patches because those branches do not have the same 13.x startup
deserializer validation hook to intercept. For those branches the portable
crash fix is the earlier read-only heap reference bounds check, which prevents a
bad snapshot reference from aborting before useful disassembly can be printed.

## Node matrix gate

The lightweight matrix runner was tightened into a CI-style gate:

- self-generated `v8asm` cache must pass asm, strict disasm, and level-4 Python
  decompile for every existing binary in the matrix;
- bytenode cache only attempts forced disassembly when numeric V8 and pointer
  compression both match;
- numeric or pointer-layout mismatches must skip forced deserialization;
- crash signatures such as SIGSEGV, CHECK/DCHECK failures, and sanitizer
  failures make the script exit non-zero;
- missing optional Node versions or optional `v8asm` binaries are warnings by
  default, and can be promoted with `VERSION_MATRIX_REQUIRE_NODES=1` or
  `VERSION_MATRIX_REQUIRE_BINS=1`.

Node 18 and 20 were installed through nvm to identify their current V8 major
lines:

| Node | V8 | pointer compression | sandbox |
| --- | --- | --- | --- |
| `v18.20.8` | `10.2.154.26-node.39` | false | false |
| `v20.20.2` | `11.3.244.8-node.38` | false | false |
| `v22.17.0` | `12.4.254.21-node.26` | false | false |
| `v24.7.0` | `13.6.233.10-node.26` | false | false |

The current matrix run covered Node 18/20/22/24. Node 18 is covered by the
cached `tests/decomp_rounds/bin_cache/v8asm.10.2.node18.x64.release/v8asm`
build, and Node 20 is covered by
`tests/decomp_rounds/bin_cache/v8asm.11.3.node20.x64.release/v8asm`. Both
matching rows have numeric and pointer matches and pass forced disasm plus
level-4 Python decompile. Existing binaries passed their self-cache checks,
mismatch rows skipped forced deserialization, optional missing `out/*` binaries
were warnings, and the gate summary reported zero failures.

## Remaining gap

This is still forced recovery. The output is useful, but not equivalent to running an Electron-matching V8 build. The read-only snapshot now matches when `v8_context_snapshot.bin` is used, and the read-only heap fallback disappears. The remaining mismatch evidence is:

- cached-data `magic`: `.jsc`/Electron snapshot uses external reference table size `1671`, current vanilla V8 build uses `1672`;
- `flags_hash`: `.jsc` has `0x59eeb3ef`, current build has `0x3c779525`.

The next higher-quality path is to reproduce Electron's exact V8 build flags and external-reference table for this `13.4.114.21-electron.0` line. If that is not practical, the current fallback is the right failure mode: no abort, visible diagnostics, matching read-only snapshot, and usable bytecode/object recovery.

## Reproduction commands

```bash
# In the official V8 checkout. Keep existing out dirs; do not clobber caches manually.
source /home/aynakeya/workspace/tmp/v8test/start_env.md
cd /home/aynakeya/workspace/tmp/v8test/v8
git checkout 13.4.114.21
gclient sync --with_branch_heads --with_tags
git apply --3way /home/aynakeya/workspace/v8asm/v8patch/v8asm-13.4.patch
gn gen out/v8asm.13.4.electron.x64.release --args='is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_embedder_string="-electron.0"'
autoninja -j10 -C out/v8asm.13.4.electron.x64.release v8asm

V8ASM=/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.13.4.electron.x64.release/v8asm
SNAPSHOT=/home/aynakeya/workspace/v8asm/v8context/v8_context_snapshot.bin
JSC=/home/aynakeya/workspace/v8asm/atom.compiled.dist.jsc
V8ASM_ALLOW_SNAPSHOT_EXTERNAL_REFERENCE_MISMATCH=1 $V8ASM --snapshot_blob "$SNAPSHOT" checkversion "$JSC"
V8ASM_ALLOW_SNAPSHOT_EXTERNAL_REFERENCE_MISMATCH=1 $V8ASM --snapshot_blob "$SNAPSHOT" disasm "$JSC" --force-incompatible > /tmp/atom.13.4.v8context.force.disasm.txt 2> /tmp/atom.13.4.v8context.force.disasm.err
cd /home/aynakeya/workspace/v8asm
python3 decompiler/v8decompiler.py /tmp/atom.13.4.v8context.force.disasm.txt --level 4 --runtime > /tmp/atom.13.4.v8context.force.dec.l4.js
```
