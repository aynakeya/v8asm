# v8asm

A V8 bytecode disassembler & decompiler (**In Progress**)

blog (chinese only): [a-quick-guide-to-disassemble-v8-bytecode](https://www.aynakeya.com/articles/ctf/a-quick-guide-to-disassemble-v8-bytecode/)

## Todo

- [x] disassembler
- [x] version brute force
- [ ] checksum rewrite: allow modify bytecode
- [ ] rewrite header
- [ ] decompiler
- [ ] make it works for electron :(
- [ ] some bug about 

## project struct

- checkversion: standalone bytecode version bruteforce
- v8patch: v8 patches
- decompiler: decompiler (in progress)
- ghidra/v8-bytecode: experimental Ghidra SLEIGH processor module for V8 Ignition bytecode

## decompiler quick usage

```bash
python3 decompiler/v8decompiler.py samples/main.d8.jsc.txt --level 1
python3 decompiler/v8decompiler.py samples/main.d8.jsc.txt --level 2
python3 decompiler/v8decompiler.py samples/main.d8.jsc.txt --level 3
python3 decompiler/v8decompiler.py samples/main.d8.jsc.txt --level 4 --runtime
```

### decompile levels

- level 1: linear, bytecode-aligned listing (best for reverse mapping to offsets).
- level 2: CFG structured output (`if/while`), keeps most low-level operations.
- level 3: level 2 + conservative simplification (register propagation, safer readability).
- level 4: level 3 + high-level pattern recovery (e.g. iterator state
  machine -> `for...of`, `+=` folding, string-concat return folding, bound
  method calls, dead temporary register cleanup, local context-slot closure
  name recovery).

### regression rounds

```bash
./tests/decomp_rounds/run_round.sh
```

The round tests compile each case with local `v8asm` and bytenode, disassemble
both outputs, run the level-4 Python decompiler, and write
`tests/decomp_rounds/summary.md`. The summary tracks low-level residue
(`ACCU`, register refs, raw gotos), missing translator coverage (`unknown`), and
best-effort object-print placeholders (`undefined_fallbacks`). It also counts
unique unresolved object-print failures from the disassembly
(`unresolved_objects`) and lists their low address suffixes plus
`object_chunk_offsets` and `current_ro_objects` when the selected `v8asm`
prints them. These offsets are more useful than full heap addresses because the
address base moves between runs. `current_ro_objects` shows whether a failed
address lands at a current read-only heap object start or inside another object,
which is useful for separating missing print guards from real snapshot layout
mismatches. The summary also compares bytenode placeholder constants with the
same case's self-cache constants and prints `Bytenode Placeholder Name Hints`;
use those hints to identify likely RO-heap object names while debugging
snapshot recovery, not as a Python-side substitution source. The companion
`Bytenode Placeholder Offset Summary` groups those hints by
`object_chunk_offset`, which is the stable key to use when comparing failed
objects across cases and runs. Cached-data header mismatches, including
`ro_snapshot`, are recorded so missing bytenode object/property names can be
tied back to V8/Node snapshot recovery instead of being mistaken for Python
translator loss. The report records the exact `v8asm`, Node, Node V8, and
bytenode versions used for that run.

By default, bytenode mode uses Node `24.7.0` through nvm. Override the binary or
Node version explicitly when validating another target:

```bash
V8ASM_BIN=/path/to/v8/out/v8asm.12.9.x64.release/v8asm \
ROUND_NODE_VERSION=22.17.0 \
./tests/decomp_rounds/run_round.sh
```

If the Node V8 version does not match `v8asm`, bytenode rows are
forced-incompatible research coverage, not proof that the V8 branch is a native
match. Per-case `*.checkversion.txt` files are written under
`tests/decomp_rounds/out/`.

For a lighter compatibility check across available `v8asm` binaries and local
nvm Node versions, run:

```bash
./tests/decomp_rounds/run_version_matrix.sh
```

This writes `tests/decomp_rounds/version_matrix/summary.md`. The matrix uses
one case by default, verifies self-generated `v8asm` cache strictly, and checks
bytenode cache against each `v8asm`. It requires `--force-incompatible` when
the Node V8 numeric version and pointer-compression layout both match, and skips
direct forced loads for numeric or pointer-layout mismatches by default. Set
`VERSION_MATRIX_FORCE_MISMATCH=1` only for an explicit research probe. The
default Node set is 18.20.8, 20.20.2, 22.17.0, and 24.7.0 when those versions
are installed through nvm.

The round runner follows the same snapshot convention as the matrix: if the
selected `V8ASM_BIN` has a sibling `snapshot_blob.bin`, commands are launched as
`v8asm --snapshot_blob <sibling> ...`. Set `ROUND_SNAPSHOT_BLOB=/path/to/blob`
to force a specific snapshot for bytenode `checkversion` and forced disasm
probes. In that mode, `checkversion` is invoked with `--force-incompatible` so
the expected read-only snapshot checksum is computed after loading the supplied
startup blob.

Important snapshot cache rule: a cached v8asm binary's sibling
`snapshot_blob.bin` must be the `snapshot_blob.bin` generated by that exact V8
build output directory. Do not place Electron, Node, Chromium, or app-provided
snapshots next to the cached `v8asm` binary. Keep those snapshots in a separate
location and pass them explicitly with `ROUND_SNAPSHOT_BLOB`,
`VERSION_MATRIX_SNAPSHOT_BLOB`, or `v8asm --snapshot_blob ...` for the forced
probe being tested. Electron packages can contain both `snapshot_blob.bin` and
`v8_context_snapshot.bin`; test both when validating Electron-generated
bytenode caches because the cached-data read-only checksum can match the
context snapshot. A mismatched sibling snapshot can make even metadata commands
such as `v8asm version` initialize the wrong startup data in older builds, and
it invalidates the matrix result.

Audit cached binaries before treating them as a gate:

```bash
python3 tests/decomp_rounds/check_bin_cache.py
python3 tests/decomp_rounds/check_patch_text.py
python3 tests/decomp_rounds/check_electron_snapshot_round.py
```

The default matrix automatically enumerates executable
`tests/decomp_rounds/bin_cache/*/v8asm` binaries, plus `./v8asm` when it exists.
Cached support files under `tests/decomp_rounds/bin_cache/` are used for V8
builds that are expensive to recreate. The default list deliberately avoids
stale local `out/` paths so `VERSION_MATRIX_REQUIRE_BINS=1` can be used as a
real gate; add experimental builds explicitly with `VERSION_MATRIX_V8ASM_BINS`
when probing another branch without adding it to the shared cache.

The script now behaves like a small CI gate by default:

- existing `v8asm` binaries must pass self-generated asm, strict disasm, and
  level-4 decompile;
- bytenode force-disasm is required when numeric V8 and pointer compression
  both match; numeric or pointer-layout mismatches are skipped by default;
- numeric mismatches can still be probed with `VERSION_MATRIX_FORCE_MISMATCH=1`
  for research, but any signal-style exit code such as `fail:139` is a gate
  failure rather than a warning;
- successful level-4 outputs must keep raw `goto offset_...` statements and
  missing-opcode `// 0x... @ ...` comments at zero by default; tune with
  `VERSION_MATRIX_MAX_RAW_GOTO` and `VERSION_MATRIX_MAX_UNKNOWN` only when
  deliberately recording a known regression;
- crash signatures such as SIGSEGV, CHECK/DCHECK failures, and sanitizer errors
  are failures;
- `<undefined: segmentfault...>` placeholders are recorded as
  `undefined_fallbacks`; set `VERSION_MATRIX_MAX_UNDEFINED_FALLBACKS` to make
  them fatal for a focused run;
- missing optional Node versions or optional `v8asm` binaries are warnings
  unless `VERSION_MATRIX_REQUIRE_NODES=1` or `VERSION_MATRIX_REQUIRE_BINS=1`.

## cached-data compatibility

`v8asm disasm` validates the cached-data header before deserializing. Matching the
numeric V8 version hash is not enough: `magic`, `flags_hash`, and the read-only
snapshot checksum must also match the current `v8asm` build.

```bash
./v8asm checkversion sample.jsc
./v8asm disasm sample.jsc
./v8asm disasm sample.jsc --force-incompatible  # best-effort research fallback
```

Use `--force-incompatible` only when intentionally inspecting cache from a
different embedder/build, such as Node/bytenode cache with a vanilla V8 build.
The V8 patches also bypass V8's internal `SerializedCodeData::SanityCheck*`
rejection path in forced mode, so `--force-incompatible` reaches the real
deserializer even when the cached-data `magic` or flags hash does not match.
Before entering V8's deserializer, `v8asm` still verifies that the current V8
header layout can parse a plausible payload length. A length outside the file,
or a zero payload length while payload bytes are present, is treated as a
different major-header layout. `v8asm` also recognizes common Node/Electron V8
version hashes and warns when forced mode is crossing a V8 major version.
Plausible mismatches enter V8 in forced mode, but the warning is intentional:
cross-major bytecode layouts can still abort inside V8 and should normally be
handled with a matching major-version patch/build.
For Electron samples, pass the matching startup snapshot explicitly when it is
available:

```bash
./v8asm --snapshot_blob v8context/v8_context_snapshot.bin \
  disasm atom.compiled.dist.jsc --force-incompatible

./v8asm --snapshot_blob v8context/v8_context_snapshot.bin \
  checkversion atom.compiled.dist.jsc --force-incompatible
```

The snapshot must match the V8 baseline used to build `v8asm`. For example,
a `13.4.114.21-electron.0` snapshot is valid for the matching 13.4 Electron
build, not for a `13.2.152.41-electron.0` v8asm. Cross-baseline startup
snapshots may still abort inside V8 even when forced version checks are
bypassed.
`Check failed: <bool> == fixed_offset` in `read-only-deserializer.cc` means the
v8asm binary's `V8_STATIC_ROOTS_BOOL` does not match whether the loaded
snapshot was serialized with fixed read-only roots. Build a matching
`v8_enable_static_roots=true` or `false` v8asm variant and treat it as a
best-effort snapshot-specific probe rather than patching over the cached-data
header checks.
For the 13.2 Electron line, keep the normal Electron build for official
Electron 34.3.0 snapshots, and build the non-static-roots probe separately:

```bash
cd /home/aynakeya/workspace/tmp/v8test
source start_env.md
cd v8
gn gen out/v8asm.13.2.152.41.electron.nostaticroots.x64.release --args='is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_enable_sandbox=true v8_embedder_string="-electron.0" v8_enable_static_roots=false'
autoninja -j10 -C out/v8asm.13.2.152.41.electron.nostaticroots.x64.release v8asm
```

The cached special probe, when present, lives at
`tests/decomp_rounds/bin_cache/v8asm.13.2.152.41.electron.nostaticroots.x64.release/`.
For the Atom 13.4 context snapshot in `v8context/v8_context_snapshot.bin`, the
matching best-effort build is the explicit static-roots Electron variant:

```bash
cd /home/aynakeya/workspace/tmp/v8test
source start_env.md
cd v8
gn gen out/v8asm.13.4.114.21.electron.staticroots.x64.release --args='is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_enable_sandbox=true v8_embedder_string="-electron.0" v8_enable_static_roots=true'
autoninja -j10 -C out/v8asm.13.4.114.21.electron.staticroots.x64.release v8asm
```

The cached special probe, when present, lives at
`tests/decomp_rounds/bin_cache/v8asm.13.4.114.21.electron.staticroots.x64.release/`.

When `--snapshot_blob` and `--force-incompatible` are used together, `v8asm`
opens the forced snapshot recovery switches before V8 startup data is loaded.
This lets an Electron context snapshot with a version string such as
`13.4.114.21-electron.0` initialize a plain `13.4.114.21` research build. The
version mismatch is printed on stderr and strict mode remains unchanged.
Startup snapshots from a different V8 baseline are attempted only in forced
mode. The 13.6 patch has additional recovery probes for read-only heap
post-processing, shared string-table insertion, external-reference-table
sentinels, and root synchronization, but a 13.6 binary still cannot reliably
initialize the 13.4 Electron startup snapshot because the startup root stream
layout diverges after those checks. Use the matching V8 baseline when the goal
is usable output. In forced Node/bytenode rounds, newer 13.6 builds also print
the current read-only heap object range for object-print failures; addresses
that consistently land inside current RO objects point at snapshot/layout
mismatch, not merely a missing printer guard.

The matrix runner uses `--snapshot_blob` automatically when a cached v8asm
binary has a sibling `snapshot_blob.bin`. Metadata commands (`version` and
`build-args`) never receive a snapshot override, so they cannot be polluted by
startup snapshot warnings from older cached builds. Strict commands use a
snapshot only for sibling blobs; an explicit override is used only for forced
commands and only when the `v8asm` binary contains the forced snapshot recovery
hook.
Bytenode `checkversion` rows also pass `--force-incompatible`, so an override
snapshot affects the header comparison instead of only the following disasm.
Override that for embedder snapshots, for example:

```bash
VERSION_MATRIX_SNAPSHOT_BLOB=v8context/v8_context_snapshot.bin \
  tests/decomp_rounds/run_version_matrix.sh
```

## v8 patch variants

- `v8patch/v8asm.patch`: current 13.6-oriented patch, verified on
  `13.6.233.10`. It includes global `--snapshot_blob`, internal cached-data
  sanity bypass, direct forced-load payload plausibility guards, forced
  cross-major cached-data warnings, and the forced snapshot version mismatch
  bypass. It is not a usable recovery path for the 13.4 Electron Atom snapshot.
- `v8patch/v8asm-13.2.patch`: V8 13.2 adaptation, verified on
  `13.2.152.41` with Electron-style, Electron no-static-roots, and Node-style
  build args. The cached `v8asm.13.2.152.41.electron.x64.release` build passes
  the Electron 34.3.0 snapshot round with both Electron package snapshots. The
  cached `v8asm.13.2.152.41.node.x64.release` build uses
  `v8_enable_pointer_compression=false` and `v8_enable_sandbox=false`, passes
  explicit self `--snapshot_blob` asm/checkversion/disasm and level-4
  decompile. The no-static-roots Electron cache is a best-effort probe for
  snapshots that fail with `Check failed: true == fixed_offset`.
- `v8patch/v8asm-13.4.patch`: V8 13.4 adaptation used for the Electron
  `atom.compiled.dist.jsc` recovery notes. It adds `--snapshot_blob`, a
  direct V8 `SerializedCodeData::SanityCheck*` bypass for forced incompatible
  loads, a forced snapshot version mismatch bypass, a research-only Electron
  startup snapshot external-reference-table bypass, and keeps the other V8
  deserializer checks intact. The explicit
  `v8asm.13.4.114.21.node.x64.release` build uses
  `v8_enable_pointer_compression=false` and `v8_enable_static_roots=false`,
  and passes explicit self `--snapshot_blob` asm/checkversion/disasm plus
  level-4 decompile. The explicit
  `v8asm.13.4.114.21.electron.staticroots.x64.release` build uses
  `v8_enable_static_roots=true`; it loads `v8context/v8_context_snapshot.bin`
  for `atom.compiled.dist.jsc` without the `fixed_offset` failure.
- `v8patch/v8asm-12.4.patch`: V8 12.4 adaptation. Node 22/bytenode needs a
  separate no-pointer-compression build of this branch. Verified on
  `12.4.254.21` with both the normal and Node22-like build args. The cached
  `tests/decomp_rounds/bin_cache/v8asm.12.4.node22.x64.release/v8asm`
  build passes self-cache and Node22/bytenode forced disasm/decompile. This
  branch has the `--snapshot_blob`, cached-data sanity bypass, direct
  forced-load payload plausibility guards, forced cross-major warnings, forced
  snapshot version mismatch bypass; it does not have the 13.x startup
  external-reference-table validation hook.
- `v8patch/v8asm-12.9.patch`: V8 12.9 adaptation, verified on `12.9.109`. It
  preserves the 12.x TrustedObject sandbox guard in `objects-printer.cc` and
  includes the Electron recovery fixes from 13.4, including forced snapshot
  version mismatch handling.
- `v8patch/v8asm-11.9.patch`: V8 11.9 adaptation, verified on `11.9.172`. It
  uses the 11.x `CodeSerializer::Deserialize(..., ScriptOriginOptions())` API
  and older object-cast helpers. This branch has the `--snapshot_blob`,
  cached-data sanity bypass, and forced snapshot version mismatch bypass; it does not have the 13.x startup
  external-reference-table validation hook.
- `v8patch/v8asm-10.2.patch`: V8 10.2 adaptation for Node 18/bytenode
  (`v18.20.8`, V8 `10.2.154.26-node.39`). It uses the older cached-data header
  shape without a read-only snapshot checksum, keeps global `--snapshot_blob`,
  bypasses internal cached-data sanity checks for forced recovery, adds direct
  forced-load payload plausibility guards, forced cross-major warnings, adds
  forced snapshot version mismatch bypass. Verified with the cached
  `tests/decomp_rounds/bin_cache/v8asm.10.2.node18.x64.release/v8asm`;
  self-cache and Node18/bytenode forced disasm/decompile both pass.
- `v8patch/v8asm-11.3.patch`: V8 11.3 adaptation for Node 20/bytenode
  (`v20.20.2`, V8 `11.3.244.8-node.38`). It uses the older `Object` member
  predicate API, moves the short-print segfault guard to `src/objects/objects.cc`,
  and treats the read-only snapshot checksum as unavailable because the V8 11.3
  cached-data header does not contain that field. It includes the direct
  forced-load payload plausibility guards, forced cross-major warnings, and
  forced snapshot version mismatch bypass. Verified with
  `tests/decomp_rounds/bin_cache/v8asm.11.3.node20.x64.release/v8asm`;
  self-cache and Node20/bytenode forced disasm/decompile both pass.

## some command for myself

apply patches

```bash
git apply --check v8asm.patch
git apply --3way v8asm.patch
```

generate patch

```bash
git diff --staged > v8asm.patch
```

## Reference:

- [View8](https://github.com/suleram/View8)
- check out my blog post
