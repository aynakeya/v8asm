# v8asm forced snapshot and Node 24 notes

Date: 2026-06-15

## Context

The goal was to avoid papering over missing output with print guards and to
identify why `v8asm` crashed or silently failed on common modern cached-data
inputs.

Two samples drove this round:

- Node 24/bytenode round cases generated with bytenode `1.5.7`.
- `atom.compiled.dist.jsc` plus `v8context/v8_context_snapshot.bin`, whose
  snapshot version string is `13.4.114.21-electron.0`.

## Node 24/bytenode

Node `v24.7.0` reports V8 `13.6.233.10-node.26` with:

```text
v8_enable_pointer_compression=0
v8_enable_sandbox=0
node_use_node_snapshot=true
```

The default V8 13.6 release build had pointer compression enabled, so forcing
Node24 bytenode cache into it crashed inside
`ObjectDeserializer::Deserialize()`. That was a build-shape mismatch, not a
Python decompiler bug.

The working build is:

```bash
gn gen out/v8asm.13.6.node24.x64.release \
  --args='is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=false v8_enable_sandbox=false'
autoninja -j10 -C out/v8asm.13.6.node24.x64.release v8asm
```

With that binary, `tests/decomp_rounds/run_round.sh` passes all 20 cases for
both self-cache and Node24/bytenode modes. The bytenode rows still show
`magic,flags_hash,ro_snapshot` mismatches because Node uses an embedder build
and snapshot, but the cached payload is readable.

## Snapshot forcing

`--snapshot_blob ... --force-incompatible` now opens the startup snapshot
mismatch path directly. Strict mode remains unchanged.

For `13.4.114.21` plain V8 plus Electron's
`13.4.114.21-electron.0` context snapshot, this is useful and produces the atom
disassembly.

For `13.6.233.10` plus the same 13.4 Electron startup snapshot, direct forcing
still does not produce usable output. The failures happen before cached-data
deserialization:

- no-pointer-compression 13.6 aborts on fixed-offset read-only-page encoding;
- pointer-compression 13.6 reaches read-only heap post-processing and then
  shared string-table/startup root layout mismatches;
- after correcting the external-reference sentinel range, the stream still
  diverges in startup root synchronization and unknown startup bytecode.

Conclusion: cross-baseline startup snapshots can be probed, but the recovery
path for usable output is still the matching V8 baseline and matching build
flags.

## Test guard

`tests/decomp_rounds/analyze_round.py` now has an explicit `status` column and
the shell runners no longer rely on a hand-written disasm command to exercise
startup snapshots:

- `run_round.sh` uses a sibling `snapshot_blob.bin` for `V8ASM_BIN` when one is
  present, or `ROUND_SNAPSHOT_BLOB` when explicitly provided.
- bytenode `checkversion` is invoked with `--force-incompatible`, so a supplied
  snapshot blob changes the expected read-only snapshot checksum in diagnostics
  before the forced disasm attempt.
- `run_version_matrix.sh` applies the same rule for bytenode header rows,
  keeping header diagnostics and forced disasm on the same startup snapshot.

It returns non-zero for `disasm_failed`, `decompile_failed`, `disasm_skipped`,
`crash_signature`, and missing outputs. `run_round.sh` records Node build flags
and skips bytenode force-disasm when pointer compression differs, so a crash is
reported as a real failure instead of appearing as a zero-residue decompile.
`run_version_matrix.sh` now also records `raw`, `unknown`, and `undef` quality
counts for every successful level-4 output. The defaults fail on any raw
`goto offset_...` statement or missing-opcode `// 0x... @ ...` comment, while
`undefined_fallbacks` remain a visible count unless a focused run sets
`VERSION_MATRIX_MAX_UNDEFINED_FALLBACKS`. The matrix also skips numeric V8
mismatches by default now; `VERSION_MATRIX_FORCE_MISMATCH=1` is only for
research probes, and a signal-style result such as `fail:139` is promoted to a
hard gate failure.
The summary now also counts unique unresolved object-print failures in the
disassembly and emits a low-address-suffix / `object_chunk_offset` table. Newer
13.6 `v8asm` builds print that offset in both `!0x... segmentfault` lines and
guarded `<undefined: segmentfault...>` placeholders. That keeps bytenode
`undefined_fallbacks` tied to concrete read-only heap offsets even when the full
heap address base changes between runs.
`Bytenode Placeholder Offset Summary` then groups the self-cache name hints by
that offset, making repeated failures such as `0xde48` visible as one RO-heap
investigation target instead of several unrelated placeholder strings.

The follow-up 13.6 build also annotates top-level object-print failures with the
current V8 read-only heap object range:

```text
current_ro_object=[0xa6f0,0xa708) delta=0x10 hit=inside
```

In the Node24 round, several unresolved bytenode names land inside current
13.6 RO objects at `+0x10`, not at object starts. That is useful evidence that
the remaining missing names are caused by Node/embedder snapshot layout
mismatch. It is not a Python prettifier problem, and blindly recovering names in
postprocess would hide the real V8-side incompatibility.

The next patch moves the same boundary probe into
`HeapObjectShortPrint`'s guarded fallback. Constant-pool placeholders now keep
their stable `object_chunk_offset` and can also carry:

```text
area_offset=0xde38 current_ro_object=[0xde38,0xde50) delta=0x10 hit=inside
```

This matters because the earlier matrix could only attach
`current_ro_object` to top-level `!0x... segmentfault` discovery/print lines.
If a missing bytenode name only appeared as a field-level short-print
placeholder, the report still had the offset but not the current vanilla
read-only object boundary. With the new fallback, those rows can show whether
the unresolved tagged address lands inside a current RO object, outside the
current RO allocation area, outside RO space, or whether even diagnostics could
not safely inspect the address.

The field-level fallback was also synced into the `13.4.114.21` Electron patch.
That matters for `atom.compiled.dist.jsc`: the correct
`v8_context_snapshot.bin` currently produces no `undefined_fallbacks`, but if a
future Electron sample regresses into guarded short-print failures the 13.4
build will now report the same `object_chunk_offset`, `area_offset`, and
`current_ro_object=[start,end)` evidence instead of only printing a generic
placeholder. The 13.4 patch was validated with
`git apply --3way --check` on a clean tag and rebuilt with `autoninja -j10`.
