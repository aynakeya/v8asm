# Electron Atom JSC recovery notes for V8 13.4

Date: 2026-06-14, updated 2026-06-15

Target sample: `atom.compiled.dist.jsc`

## Summary

`atom.compiled.dist.jsc` is raw V8 cached data from an Electron build. The version hash resolves to V8 `13.4.114.21`, so the V8 checkout was moved to the official `13.4.114.21` tag and synchronized with `gclient sync --with_branch_heads --with_tags` using the local `start_env.md` depot_tools/proxy setup.

The plain V8 13.4 build does not exactly match Electron cached data. `checkversion` reports the same V8 version hash, but different cached-data `magic` and `flags_hash`. Strict deserialization correctly refuses the file. The matching context snapshot also carries the Electron version suffix `13.4.114.21-electron.0`, so a plain `13.4.114.21` build needs an explicit forced startup-snapshot path before it can inspect the cached-data payload.

The current fix is intentionally narrow. With the correct context snapshot, the read-only snapshot checksum matches and `ReadReadOnlyHeapRef` fallback is not needed. The remaining V8-side incompatibility is the startup external-reference alias table: the Electron snapshot serializes table size `1671`, while the vanilla 13.4 build has `1672`. In forced mode, `v8asm` now enables one startup external-reference compatibility hook, infers the Electron sentinel from the snapshot magic, and keeps V8's other deserializer checks intact.

After the matching files were added under `v8context/`, the correct startup blob for this `.jsc` turned out to be `v8context/v8_context_snapshot.bin`, not `v8context/snapshot_blob.bin`. Its header contains read-only snapshot checksum `0x4e6b3214`, exactly matching `atom.compiled.dist.jsc`.

`v8_context_snapshot.bin` was produced by the Electron line and carries snapshot
version string `13.4.114.21-electron.0`. A plain V8 `13.4.114.21` build
originally aborted in `SnapshotImpl::CheckVersion` before `v8asm` could inspect
the cached-data header. The 2026-06-15 patch makes this a forced-mode behavior:
when `--snapshot_blob` and `--force-incompatible` are both present, `v8asm`
enables `V8ASM_ALLOW_SNAPSHOT_VERSION_MISMATCH=1` before V8 startup data is
loaded. The mismatch is printed on stderr and initialization continues.

That bypass is useful for the same V8 baseline plus embedder suffix case.
Rebuilding patched `13.6.233.10` binaries and pointing them at the
`13.4.114.21-electron.0` startup snapshot showed why a matching baseline is
still required for usable output. A Node24-like no-pointer-compression 13.6
build aborts immediately on the fixed-offset read-only-page encoding used by
the Electron snapshot. A pointer-compression 13.6 build gets further, but then
hits read-only heap post-processing, shared string-table insertion, startup
external-reference sentinel, and root synchronization differences before the
cached-data file is even deserialized. The 13.6 patch now allows this path only
with explicit `--force-incompatible` and prints each forced recovery step, but
the result is still not a usable atom recovery path. The practical fix remains
using the matching `13.4.114.21` v8asm build with
`v8context/v8_context_snapshot.bin`.

The same Electron snapshot also has serialized external reference table size
`1671`, while the vanilla V8 `13.4.114.21` build has size `1672`; in startup
deserialization that means the Electron sentinel is `1592` and the current
binary sentinel is `1593`. The research-only external-reference-table hook
infers the snapshot sentinel from the snapshot magic and continues, but only
when the user explicitly asks for forced incompatible recovery.

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

Header check with `v8context/v8_context_snapshot.bin` and the plain 13.4 build:

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

Strict mode result for cached data without `--force-incompatible`:

```text
Refusing to deserialize incompatible cached data. Use --force-incompatible for best-effort recovery.
```

Earlier forced crash when the wrong snapshot was used:

```text
../../third_party/libc++/src/include/__vector/vector.h:399: assertion __n < size() failed: vector[] index out of bounds
#6  Deserializer<Isolate>::ReadReadOnlyHeapRef(...)
#7  Deserializer<Isolate>::ReadObject(...)
#52 ObjectDeserializer::Deserialize()
#54 CodeSerializer::Deserialize(...)
#55 do_disasm(...)
```

After using `v8_context_snapshot.bin`, forced disassembly no longer reports
invalid read-only heap references:

```text
/tmp/atom.13.4.v8context.force.disasm.txt   112391 lines, 6452189 bytes
/tmp/atom.13.4.v8context.force.disasm.err        9 lines,     400 bytes
```

The Python decompiler handles this output and produces level-4 pseudo JS with
runtime helpers:

```text
/tmp/atom.13.4.v8context.force.dec.l4.js       36038 lines, 1187504 bytes
/tmp/atom.13.4.v8context.force.decompile.err       0 bytes
```

Plain V8 13.4 forced snapshot recovery after the 2026-06-15 patch:

```text
/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.13.4.x64.release/v8asm \
  --snapshot_blob /home/aynakeya/workspace/v8asm/v8context/v8_context_snapshot.bin \
  checkversion /home/aynakeya/workspace/v8asm/atom.compiled.dist.jsc \
  --force-incompatible

Warning: forcing snapshot blob version tag mismatch.
#   V8 binary version: 13.4.114.21
#    Snapshot version: 13.4.114.21-electron.0
Warning: forcing snapshot version mismatch.
#   V8 binary version: 13.4.114.21
#    Snapshot version: 13.4.114.21-electron.0
# The snapshot consists of 702157 bytes and contains 3 context(s).
v8asm: using snapshot external reference table size 1671 (current 1672), inferred startup sentinel 1592 (current 1593)
Version hash: hex = 8dfe3521 , uint32 = 0x2135fe8d (557186701)
Known matching version: 13.4.114.21
```

The same plain build now forced-disassembles the Atom sample without fatal
signals and the Python level-4 decompiler consumes the output:

```text
/tmp/atom.13.4.current.v8context.force.disasm.txt       112391 lines, 6452189 bytes
/tmp/atom.13.4.current.v8context.force.disasm.err           16 lines,     726 bytes
/tmp/atom.13.4.current.v8context.force.dec.l4.js         28187 lines,  879244 bytes
/tmp/atom.13.4.current.v8context.force.decompile.err         0 lines,       0 bytes
```

The final verification command used the correct version and snapshot directly,
without manually setting environment variables:

```bash
/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.13.4.x64.release/v8asm \
  --snapshot_blob /home/aynakeya/workspace/v8asm/v8context/v8_context_snapshot.bin \
  disasm /home/aynakeya/workspace/v8asm/atom.compiled.dist.jsc \
  --force-incompatible > /tmp/atom.13.4.current.v8context.force.disasm.txt \
  2> /tmp/atom.13.4.current.v8context.force.disasm.err

python3 /home/aynakeya/workspace/v8asm/decompiler/v8decompiler.py \
  /tmp/atom.13.4.current.v8context.force.disasm.txt --level 4 --runtime \
  > /tmp/atom.13.4.current.v8context.force.dec.l4.js \
  2> /tmp/atom.13.4.current.v8context.force.decompile.err
```

## Code changes from this pass

- Added `v8patch/v8asm-13.4.patch` for the V8 `13.4.114.21` tag.
- Added a v8asm-global `--snapshot_blob <file>` option so the matching Electron
  snapshot can be passed directly instead of using an executable-side symlink.
- Patched V8's `SerializedCodeData::SanityCheck*` path for research forced
  recovery. When `v8asm` has already accepted `--force-incompatible`, V8 no
  longer rejects the cached data a second time because the cached-data `magic`
  or flags hash differs.
- Added a forced-mode snapshot version mismatch bypass in
  `src/snapshot/snapshot.cc`. `v8asm` enables it before V8 initialization only
  when `--snapshot_blob` and `--force-incompatible` are both present.
- Added `V8ASM_ALLOW_SNAPSHOT_EXTERNAL_REFERENCE_MISMATCH=1` as a research-only
  startup snapshot compatibility switch for Electron external-reference table
  size drift. `v8asm` sets it only for `--snapshot_blob` plus
  `--force-incompatible`.
- Kept the diagnostic visible on stderr so partial recovery is not mistaken for native compatibility.
- Updated Python decompiler input reading to use UTF-8 replacement mode. V8 object printing can emit non-UTF-8 bytes for corrupted or embedder-specific string data.
- Updated `V8String.parse()` to parse both `#value` and quoted string payloads such as `[String]: "...\x0a..."`; only missing payloads fall back to an address-derived placeholder.
- Added tests for non-UTF-8 disassembly input, missing string value fallback, and quoted V8 string payloads.

Validation run:

```text
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 114 tests in 0.022s
OK
```

Patch usability check:

```text
git apply --check --reverse /home/aynakeya/workspace/v8asm/v8patch/v8asm-13.4.patch

git worktree add --detach /tmp/v8applycheck-10.2 10.2.154.26
git -C /tmp/v8applycheck-10.2 apply --check /home/aynakeya/workspace/v8asm/v8patch/v8asm-10.2.patch

git worktree add --detach /tmp/v8applycheck-11.3 11.3.244.8
git -C /tmp/v8applycheck-11.3 apply --check /home/aynakeya/workspace/v8asm/v8patch/v8asm-11.3.patch

git worktree add --detach /tmp/v8applycheck-11.9 11.9.169.7
git -C /tmp/v8applycheck-11.9 apply --check /home/aynakeya/workspace/v8asm/v8patch/v8asm-11.9.patch

git worktree add --detach /tmp/v8applycheck-12.4 12.4.254.21
git -C /tmp/v8applycheck-12.4 apply --check /home/aynakeya/workspace/v8asm/v8patch/v8asm-12.4.patch

git worktree add --detach /tmp/v8applycheck-12.9 12.9.202.28
git -C /tmp/v8applycheck-12.9 apply --check /home/aynakeya/workspace/v8asm/v8patch/v8asm-12.9.patch

git worktree add --detach /tmp/v8applycheck-13.4 13.4.114.21
git -C /tmp/v8applycheck-13.4 apply --check /home/aynakeya/workspace/v8asm/v8patch/v8asm-13.4.patch

git worktree add --detach /tmp/v8applycheck-13.6 13.6.233.10
git -C /tmp/v8applycheck-13.6 apply --check /home/aynakeya/workspace/v8asm/v8patch/v8asm.patch
```

All checks passed. Existing V8 build output caches were not manually deleted.

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

2026-06-15 recheck: the externally supplied `v8_context_snapshot.bin` path is
verified with the plain `out/v8asm.13.4.x64.release/v8asm` build. The cached
Electron-suffix build still passes self-cache checks, but mixing it with this
external context snapshot aborts during V8 startup with
`Check failed: address == encoded_address`; keep that binary for self-cache
coverage, not for the explicit `--snapshot_blob v8_context_snapshot.bin`
recovery path.

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
Existing `out/*` build caches were not manually deleted; when the official V8
landmine step clobbered `out/*`, the rebuilt support files were copied into the
local `tests/decomp_rounds/bin_cache/` cache before switching versions again.

| patch | V8 tag used | synced Electron fixes | build/test status |
| --- | --- | --- | --- |
| `v8patch/v8asm.patch` | `13.6.233.10` | `--snapshot_blob`, cached-data sanity bypass, forced snapshot suffix/baseline mismatch attempt, direct forced-load payload guard and cross-major warning | patch applies on clean `13.6.233.10`; 13.6 is not a usable Atom path for the 13.4 Electron startup snapshot |
| `v8patch/v8asm-13.4.patch` | `13.4.114.21` | `--snapshot_blob`, cached-data sanity bypass, forced same-baseline snapshot suffix mismatch, startup external-reference mismatch opt-in | `autoninja -j10 -C out/v8asm.13.4.x64.release v8asm`; plain build forced-disassembles `atom.compiled.dist.jsc` with `v8_context_snapshot.bin`; level-4 decompiler passed |
| `v8patch/v8asm-12.9.patch` | `12.9.202.28` | `--snapshot_blob`, cached-data sanity bypass, forced same-baseline snapshot suffix mismatch | `git apply --check` passed on clean `12.9.202.28` |
| `v8patch/v8asm-12.4.patch` | `12.4.254.21` | `--snapshot_blob`, cached-data sanity bypass, forced same-baseline snapshot suffix mismatch, direct forced-load payload guard and cross-major warning | `git apply --check` passed on clean `12.4.254.21`; cached Node22 build still passes forced disasm/decompiler |
| `v8patch/v8asm-11.9.patch` | `11.9.169.7` | `--snapshot_blob`, cached-data sanity bypass, forced same-baseline snapshot suffix mismatch | `git apply --check` passed on clean `11.9.169.7` |
| `v8patch/v8asm-11.3.patch` | `11.3.244.8` | `--snapshot_blob`, cached-data sanity bypass, forced same-baseline snapshot suffix mismatch, direct forced-load payload guard and cross-major warning | `git apply --check` passed on clean `11.3.244.8`; cached Node20 build still passes forced disasm/decompiler |
| `v8patch/v8asm-10.2.patch` | `10.2.154.26` | `--snapshot_blob`, cached-data sanity bypass, forced same-baseline snapshot suffix mismatch | `git apply --check` passed on clean `10.2.154.26`; cached Node18 build still passes forced disasm/decompiler |

The snapshot version mismatch bypass is present in all maintained patch
variants. The startup external-reference-table mismatch switch is retained only
for the verified 13.4 Atom path, where it is required by the Electron context
snapshot's one-entry external-reference table drift.

## Direct forced-load guard

The patch intentionally lets `--force-incompatible` pass version, flags, and
read-only snapshot checksum mismatches down into V8's real deserializer. That
is required for Electron/Node research samples where the embedder snapshot or
build flags differ from a vanilla V8 checkout.

One mismatch is still stopped before V8: if the current V8 cached-data header
layout reads an impossible payload length, the bytes are being interpreted with
the wrong major-header shape. The 2026-06-15 update treats both
`payload_length > file_payload_size` and `payload_length == 0` with remaining
payload bytes as implausible.

For plausible payloads, forced mode now attempts direct recovery even when a
known version hash points at another V8 major. It prints a cross-major warning
instead of silently entering V8. This is intentional research behavior, not a
compatibility guarantee.

The same forced behavior now applies to `--snapshot_blob`: strict mode refuses
baseline-mismatched startup blobs, while `--snapshot_blob ... --force-incompatible`
sets the startup mismatch recovery flags before V8 initialization. The 13.6
patch additionally probes several startup-snapshot mismatch points, but the
13.6-vs-13.4 Electron test still fails in startup root deserialization. Matching
baseline remains the only verified path for `atom.compiled.dist.jsc`.

The 13.6 patch now also annotates unresolved read-only object-print failures
with the current read-only heap object boundary. In the Node24/bytenode round,
several unresolved offsets land inside the current RO object at `delta=0x10`
instead of on an object boundary. That is a stronger signal for
embedder-snapshot/layout mismatch than a simple missing printer guard.

The matrix runner now passes a sibling `snapshot_blob.bin` automatically for
cached `v8asm` binaries and can be pointed at an embedder snapshot with:

```bash
VERSION_MATRIX_SNAPSHOT_BLOB=v8context/v8_context_snapshot.bin \
  tests/decomp_rounds/run_version_matrix.sh
```

An explicit `VERSION_MATRIX_SNAPSHOT_BLOB` override is intentionally not used
for strict `version`, `build-args`, or self-cache `asm` commands. Those commands
would still load startup data in strict mode and can abort on an Electron
version suffix mismatch. The runner now uses the override only for forced
commands and checks the binary for the forced snapshot recovery hook statically
instead of probing by starting V8 with an intentionally mismatched snapshot.

## Node matrix gate

The lightweight matrix runner was tightened into a CI-style gate:

- self-generated `v8asm` cache must pass asm, strict disasm, and level-4 Python
  decompile for every existing binary in the matrix;
- bytenode cache requires forced disassembly when numeric V8 and pointer
  compression both match;
- numeric mismatches and pointer-layout mismatches skip forced deserialization
  by default, so incompatible serializer layouts are not fed into V8 during the
  CI gate;
- `VERSION_MATRIX_FORCE_MISMATCH=1` can still opt into research probes, but a
  signal-style exit such as `fail:139` is always a gate failure;
- crash signatures such as SIGSEGV, CHECK/DCHECK failures, and sanitizer
  failures make the script exit non-zero;
- successful level-4 outputs now also carry a `quality` field. By default
  `raw_goto` and missing-opcode `unknown` comments must stay at zero; tune
  `VERSION_MATRIX_MAX_RAW_GOTO` or `VERSION_MATRIX_MAX_UNKNOWN` only for a
  focused regression capture. `undefined_fallbacks` are recorded and can be
  made fatal with `VERSION_MATRIX_MAX_UNDEFINED_FALLBACKS`;
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

The current strict matrix run covered Node 18/20/22/24. Node 18, Node 20, and
Node 22 are covered by cached V8 builds:

| Node | cached v8asm | forced bytenode row |
| --- | --- | --- |
| `v18.20.8` | `tests/decomp_rounds/bin_cache/v8asm.10.2.node18.x64.release/v8asm` | numeric match, pointer match, forced disasm ok, level-4 decompile ok |
| `v20.20.2` | `tests/decomp_rounds/bin_cache/v8asm.11.3.node20.x64.release/v8asm` | numeric match, pointer match, forced disasm ok, level-4 decompile ok |
| `v22.17.0` | `tests/decomp_rounds/bin_cache/v8asm.12.4.node22.x64.release/v8asm` | numeric match, pointer match, forced disasm ok, level-4 decompile ok |
| `v24.7.0` | repo `v8asm` (`13.6.233.10`) | numeric match, pointer match, forced disasm ok, level-4 decompile ok |

The Electron-flavored
`tests/decomp_rounds/bin_cache/v8asm.13.4.electron.x64.release/v8asm` build
also passes self-cache asm/strict-disasm/decompile in the matrix, but it is not
the verified binary for the external `v8_context_snapshot.bin` recovery path.
The plain `out/v8asm.13.4.x64.release/v8asm` build was restored on 2026-06-15
and passes self-cache asm, strict disasm, level-4 decompile, and the explicit
`--snapshot_blob v8context/v8_context_snapshot.bin` Atom forced disasm.
Mismatch rows skipped forced deserialization when pointer compression differed.
The remaining missing optional plain `out/*` binaries in the latest matrix are
11.9, 12.4, and 12.9.

The 2026-06-15 strict gate
(`/tmp/v8asm-matrix-full-strict-after-snapshot-force/summary.md`) reported zero
failures. Required same-major rows passed forced disasm and level-4 decompile
for Node 18/V8 10.2, Node 20/V8 11.3, Node 22/V8 12.4, and Node 24/V8 13.6.
Pointer-compatible cross-major rows were probed and returned ordinary `fail:1`;
a crash-signature scan for fatal errors, CHECK failures, assertions, SIGSEGV,
SIGTRAP, and abort messages returned no matches.

## Bytenode undefined fallbacks

The remaining bytenode `undefined_fallbacks` are now tracked with cached-data
header evidence in `tests/decomp_rounds/summary.md`. The 2026-06-15 Node 24
round shows:

- every self-generated `v8asm` row has `header_mismatch=ok` and
  `ro_snapshot=ok`;
- every bytenode row has `header_mismatch=magic,flags_hash,ro_snapshot` and
  `ro_snapshot=mismatch`;
- cases with missing object/property names, such as `05_object_calls`,
  `07_try_catch`, `09_all_features`, `11_object_mutation`,
  `13_destructuring_spread`, `14_optional_chaining`, `16_regex_template`, and
  `20_rest_spread_calls`, are all inside that bytenode RO snapshot mismatch
  set.

That means the current gaps are not caused by Python translator coverage: the
level-4 summary still has `raw_goto=0`, `unknown=0`, and `accu_lines=0`. The
missing names are already absent in the `v8asm` object print, where constants
fall back to markers such as `<undefined: segmentfault, might outside scope>`.

The analyzer now separates placeholder occurrences from unique failed objects.
Full heap addresses move between runs, but the low address suffixes stayed
stable across a fresh Node 24 round. The 13.6 `v8asm` build now also annotates
both top-level object-print crashes and guarded `HeapObjectShortPrint`
placeholders with `object_chunk_offset`. That offset is the untagged heap-object
address within the current memory chunk, so it is a better RO-heap locator than
the full process address. For top-level print/discovery crashes, it also prints
`current_ro_object=[start,end) delta=... hit=...`; `hit=inside` shows that the
Node object pointer resolves into the middle of a current V8 RO object, which
keeps the investigation focused on snapshot/build alignment.

`tests/decomp_rounds/analyze_round.py` now adds `Bytenode Placeholder Name
Hints`, by comparing the bytenode constant-pool placeholder at `(function name,
constant-pool index)` with the same case's self-cache constant-pool value. It
also emits `Bytenode Placeholder Offset Summary`, which groups those hints by
`object_chunk_offset`. This is still diagnostic evidence for snapshot/RO-heap
recovery, not a Python replacement rule, but it removes most of the manual
guessing:

| suffix | object chunk offset | cases | self-cache value hint |
|---|---:|---|---|
| `de49` | `0xde48` | `05_object_calls`, `09_all_features`, `16_regex_template` | `"toUpperCase"` |
| `ee79` | `0xee78` | `07_try_catch`, `09_all_features` | `"JSON"` |
| `e089` | `0xe088` | `07_try_catch`, `09_all_features` | `"parse"` |
| `08e1` | `0x108e0` | `11_object_mutation` | `"seen"`, `"count"` |
| `d321` | `0xd320` | `13_destructuring_spread` | `"values"` |
| `0919` | `0x10918` | `14_optional_chaining` | `"address"`, `"profile"` |
| `a701` | `0xa700` | `20_rest_spread_calls` | `"right"` |
| `d479` | `0xd478` | `20_rest_spread_calls` | `"collect"` |
| `eed1` | `0xeed0` | `20_rest_spread_calls` | `":"` |
| `f0e1` | `0xf0e0` | `20_rest_spread_calls` | `"Math"` |

The same offset mapping across multiple cases is useful for manual triage only.
It should not be blindly patched into the Python output, because the
authoritative failure is still in V8 object recovery: Node's read-only heap
objects are being interpreted through a non-Node startup snapshot.

The local Node 24 check was rerun with the correct nvm activation:

```text
/home/aynakeya/.nvm/versions/node/v24.7.0/bin/node
v24.7.0
13.6.233.10-node.26
node_use_node_snapshot=true
v8_enable_pointer_compression=0
```

Searching the Node 24 nvm installation found no external `snapshot_blob.bin` or
`v8_context_snapshot.bin`; only `include/node/v8-snapshot.h` is present. So for
Node/bytenode, unlike the Electron sample, there is no local external snapshot
file that can simply be passed to `v8asm --snapshot_blob`. The next real
recovery path is a Node-aligned V8/v8asm build or extracting/reconstructing the
Node startup snapshot/RO heap, not another Python prettification pass.

## Decompiler cleanup pass

The 2026-06-15 level-4 Python decompiler pass now removes more dead temporary
register assignments after higher-level expressions have been recovered. It
keeps effectful calls and constructors, but drops pure temporary loads such as
saved member references, literal argument setup, and overwritten register
aliases once their values have already been inlined into a call expression.

The call rewriter also recurses into simple parenthesized binary expressions, so
patterns like:

```text
r4 = r1.sum
return (r3 + r4.call(r1))
```

now become:

```text
return (r3 + r1.sum())
```

The refreshed round summary still reports `accu_lines=0`, `raw_goto=0`, and
`unknown=0` across the checked cases. `reg_refs` dropped in the high-noise
cases, for example `20_rest_spread_calls` went from `78` to `50` in v8asm mode
and from `86` to `64` in bytenode mode. The remaining bytenode
`undefined_fallbacks` continue to line up with `ro_snapshot=mismatch`.

A follow-up file-level pass recovers some local context-slot closure names. It
uses only local evidence inside the same rendered function, either
`script_context[n] = create_closure(Name)` or a V8
`ThrowReferenceErrorIfHole` pattern rendered as `ensureDefined("Name")`
immediately before a `context_slot[n]` use. That changes the `run` case from:

```text
ensureDefined("Pair")
r1 = new context_slot[3](...r0)
```

to:

```text
ensureDefined("Pair")
r1 = new Pair(...r0)
```

The pass intentionally does not perform broad cross-function `context_slot`
replacement, because closure variables and private-field symbols share the same
printed form and would be easy to corrupt without scope-level evidence.

## Atom decompiler opcode coverage

The plain 13.4 forced disassembly exposes bytecode forms that the small round
cases did not cover, especially operand-scale suffixes such as `.Wide` and
`.ExtraWide`. Before normalizing those suffixes, level-4 output for
`atom.compiled.dist.jsc` still contained 1978 raw unknown bytecode comments.
Most of them were ordinary instructions such as `LdaSmi.Wide`,
`CreateObjectLiteral.Wide`, `DefineNamedOwnProperty.Wide`, and
`CallUndefinedReceiver2.Wide`.

The Python decompiler now strips V8 operand-scale suffixes before dispatching
to opcode translators and adds conservative translations for the Atom-heavy
opcodes: generic `CallProperty`, context-slot load/store, empty literals,
loose equality, `typeof` tests, boolean/numeric conversions, bitwise and shift
operators, mapped arguments, clone-object, and the low-level `for-in` iterator
bytecodes.

Current Atom check:

```text
python3 decompiler/v8decompiler.py \
  /tmp/atom.current.13.4.force.disasm.txt --level 4 --runtime \
  > /tmp/atom.current.13.4.force.dec.l4.final.js

unknown_comments: 0
undefined_fallbacks: 0
raw_goto: 5
functions: 809
decompiler stderr: 0 bytes
```

One remaining raw-goto source was in the Python try/catch renderer, not V8
object recovery. The renderer splits bytecode with a handler table into
prefix/try/catch/suffix fragments. If the prefix ended with a conditional guard
that jumped directly to the try/catch resume offset, that target was outside
the separately rendered prefix fragment, so the structurer had no local block
to consume and emitted `if (...) goto offset_...`.

The renderer now recognizes only the safe linear form of that pattern and emits:

```js
if (truthy(r1.length)) {
  try {
    ...
  } catch (a) {
    ...
  }
}
```

It deliberately refuses the rewrite when the prefix already contains branches
to outside the fragment, which avoids duplicating async/generator state-machine
setup code. On the Atom sample this removes the `File.reloadContent` raw guard
without hiding the remaining async/control-flow gaps.

The remaining `ACCU`/register/goto residue is now structural cleanup work, not
missing opcode coverage. The normal 20-case round still reports `raw_goto=0`
and `unknown=0` for both self-cache and bytenode rows.

2026-06-15 follow-up: the Atom sample exposed two Python decompiler correctness
bugs after the try/catch fix.

First, unused-`ACCU` cleanup was treating any following `ACCU = ...` as a hard
overwrite, even when the right-hand side read the previous accumulator. This
deleted real producers such as:

```js
ACCU = -1
ACCU = (r6 == ACCU)
```

and left misleading comparisons like `(r6 == ACCU)`. The cleanup and logical
passes now treat `ACCU = rhs` as a read before overwrite when `rhs` mentions
`ACCU`, so numeric sentinels and string constants used by the next compare are
kept.

Second, the structurer fallback for an unrecovered conditional branch used to
emit the raw `if (...) goto offset_X` line and then continue at `offset_X`.
That hides the fallthrough bytecode. In Atom this truncated a large
locale-normalization dispatch after the first `zh-CN`/`zh-Hans` case. The
fallback now keeps raw conditional gotos but continues through the fallthrough
path and tracks pending raw branch targets so intervening case bodies and the
default body are still emitted.

A follow-up level-4 switch pass now recognizes that recovered raw dispatch
shape when every target body assigns the same destination. It folds the
compare/goto table plus its case/default bodies into an object-map expression
such as:

```js
script_context[36] = ({"zh-CN": "zh-Hans", "zh-Hans": "zh-Hans"}[r0] ?? "Base")
```

This keeps the non-lossy fallback behavior while removing the large dispatch's
raw gotos from normal output.

Current forced Atom check with the correct binary and supplied snapshot:

```text
V8 binary:       13.4.114.21
snapshot blob:   13.4.114.21-electron.0
version_hash:    0x2135fe8d ok
ro checksum:     0x4e6b3214 ok
disasm stderr:   forced Electron/plain-V8 warnings only
decompile stderr: 0 bytes

score:
  functions: 809
  unknown_comments: 0
  undefined_fallbacks: 0
  raw_goto: 2
```

The recovered locale map includes keys for `zh-CN`, `zh-Hans`, `zh-TW`,
`zh-Hant`, `it`, `it-IT`, and the remaining locale aliases, with fallback
`"Base"`. A later level-4 cleanup also drops one redundant empty `if`/`else`
guard where the else branch immediately re-tests the same truthy value through
`ACCU` and jumps on the same condition. The try/catch renderer now also handles
the short-circuit guard shape where the false branch is emitted after the
try-skip jump and catch body. That restored Atom's `ensureDir(path, callback)`
fallback branch instead of leaving it behind a raw goto. The remaining two raw
gotos are separate async/control-flow structuring gaps, not missing opcode
coverage or hidden output.

## Remaining gap

This is still forced recovery. The output is useful, but not equivalent to
running an Electron-matching V8 build. The read-only snapshot checksum now
matches when `v8_context_snapshot.bin` is used, and the read-only heap fallback
disappears. The remaining mismatch evidence is:

- snapshot version string: Electron snapshot is `13.4.114.21-electron.0`,
  plain V8 is `13.4.114.21`;
- startup external reference table: Electron snapshot uses size `1671`, current
  vanilla V8 build uses `1672`;
- cached-data `magic`: `.jsc` has `0xc0de0687`, current plain V8 expects
  `0xc0de0688`;
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
gn gen out/v8asm.13.4.x64.release --args='is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true'
autoninja -j10 -C out/v8asm.13.4.x64.release v8asm

V8ASM=/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.13.4.x64.release/v8asm
SNAPSHOT=/home/aynakeya/workspace/v8asm/v8context/v8_context_snapshot.bin
JSC=/home/aynakeya/workspace/v8asm/atom.compiled.dist.jsc
$V8ASM --snapshot_blob "$SNAPSHOT" checkversion "$JSC" --force-incompatible
$V8ASM --snapshot_blob "$SNAPSHOT" disasm "$JSC" --force-incompatible > /tmp/atom.13.4.plain.force.disasm.txt 2> /tmp/atom.13.4.plain.force.disasm.err
cd /home/aynakeya/workspace/v8asm
python3 decompiler/v8decompiler.py /tmp/atom.13.4.plain.force.disasm.txt --level 4 --runtime > /tmp/atom.13.4.plain.force.dec.l4.js

# Optional closer Electron-suffix build:
cd /home/aynakeya/workspace/tmp/v8test/v8
gn gen out/v8asm.13.4.electron.x64.release --args='is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_embedder_string="-electron.0"'
autoninja -j10 -C out/v8asm.13.4.electron.x64.release v8asm
```
