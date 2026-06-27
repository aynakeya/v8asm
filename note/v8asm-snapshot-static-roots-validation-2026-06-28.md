# v8asm snapshot/static-roots validation notes

Date: 2026-06-28

## Snapshot version reader

`v8asm` validates an explicitly supplied `--snapshot_blob` before V8
initialization so that obvious cross-baseline mistakes are visible. The previous
reader assumed the snapshot version string started at offset `16`. That is true
for newer snapshots such as `13.2+`, but V8 `11.4.183.14` stores the version at
offset `12`:

```text
00000000: 01 00 00 00 01 00 00 00 36 ef 7d ee 31 31 2e 34
00000010: 2e 31 38 33 2e 31 34 00
```

This made `out/v8asm.11.4.183.14.node.x64.release/snapshot_blob.bin` look like
a cross-version snapshot even though it was produced by the same build. The
patches now try plausible version-string offsets `{16, 12, 8}` and require the
candidate to start with a digit and contain a dot before accepting it.

Fresh verification after rebuilding with `autoninja -j10`:

```text
out/v8asm.11.4.183.14.node.x64.release/v8asm --snapshot_blob <sibling> asm/checkversion/disasm 01_arith.js
status=0
asm.err=0 bytes
checkversion.err=0 bytes
disasm.err=0 bytes
decompile.err=0 bytes
Found matching version: 11.4.183.14
disasm lines: 89
level-4 decompile lines: 61
```

The validated binary was copied to
`tests/decomp_rounds/bin_cache/v8asm.11.4.183.14.node.x64.release/`. Its
sibling `snapshot_blob.bin` is the V8 build output snapshot, not an Electron or
application snapshot.

## Static roots are a build-flag compatibility issue

`Check failed: <bool> == fixed_offset` comes from
`read-only-deserializer.cc`. It means the `V8_STATIC_ROOTS_BOOL` compiled into
the `v8asm` binary disagrees with the read-only roots encoding used by the
startup snapshot. This should be handled by compiling a matching
`v8_enable_static_roots=true` or `false` v8asm variant, not by weakening the
cached-data header checks.

The special variants are best-effort probes. A failure is useful evidence about
the snapshot, not a Python decompiler failure.

## Electron 34.3.0 / V8 13.2.152.41

Validation input:

```text
electron dir: /home/aynakeya/workspace/tmp/v8test/electron-cache/v34.3.0-linux-x64
electron version: 34.3.0
snapshot_blob.bin: 13.2.152.41-electron.0
v8_context_snapshot.bin: 13.2.152.41-electron.0
```

The matching cached binary is:

```text
tests/decomp_rounds/bin_cache/v8asm.13.2.152.41.electron.x64.release/v8asm
version: 13.2.152.41-electron.0
v8_enable_pointer_compression=true
v8_enable_static_roots=true
```

Focused Electron validation:

```bash
python3 tests/decomp_rounds/check_electron_snapshot_round.py \
  --v8asm tests/decomp_rounds/bin_cache/v8asm.13.2.152.41.electron.x64.release/v8asm \
  --out /tmp/v8asm-electron-snapshot-round-normal
```

Result:

```text
snapshot_blob: checkversion=0 disasm=0 decompile=0
v8_context_snapshot: checkversion=0 disasm=0 decompile=0
electron_snapshot_round_ok=1 output=/tmp/v8asm-electron-snapshot-round-normal
```

The non-static-roots probe:

```text
tests/decomp_rounds/bin_cache/v8asm.13.2.152.41.electron.nostaticroots.x64.release/v8asm
v8_enable_static_roots=false
```

is the wrong direction for Electron 34.3.0 and aborts as expected:

```text
Check failed: false == fixed_offset.
```

So for Electron 34.3.0, use the normal `v8_enable_static_roots=true` 13.2
binary. Keep the `nostaticroots` build only for snapshots that produce the
opposite static-roots failure.
