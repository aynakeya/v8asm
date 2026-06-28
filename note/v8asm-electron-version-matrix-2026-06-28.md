# v8asm Electron version matrix, 2026-06-28

## Why this note exists

The previous focused Electron guard validated Electron 34.3.0 / V8
`13.2.152.41-electron.0`, but it was a single default path. That was useful for
the static-roots fix, but it was not a general rule that prevents accidentally
testing an Electron-generated `.jsc` with the wrong V8 baseline.

## Correction

Added `tests/decomp_rounds/check_electron_version_matrix.py`.

The script:

- enumerates local Electron releases from
  `/home/aynakeya/workspace/tmp/v8test/electron-cache`;
- reads each release's `process.versions.v8` with `ELECTRON_RUN_AS_NODE=1`;
- selects only Electron-flavored cached `v8asm` binaries whose `v8asm version`
  exactly equals that Electron V8 string;
- compiles a bytenode `.jsc` with that same Electron runtime;
- tests both release snapshots explicitly:
  - `snapshot_blob.bin`
  - `v8_context_snapshot.bin`
- runs `checkversion`, `disasm --force-incompatible`, and level-4 Python
  decompile for each snapshot.

This keeps the validation aligned with the rule that bytenode/node/electron
generated caches must be checked against the matching V8 version and embedder
shape, not a nearby major or a convenient cached binary.

## Current local coverage

Current local Electron cache:

```text
/home/aynakeya/workspace/tmp/v8test/electron-cache/v34.3.0-linux-x64
Electron: 34.3.0
V8: 13.2.152.41-electron.0
```

The matching cached `v8asm` is:

```text
tests/decomp_rounds/bin_cache/v8asm.13.2.152.41.electron.x64.release/v8asm
v8_enable_pointer_compression=true
v8_enable_static_roots=true
```

The no-static-roots probe has the same V8 version string but is intentionally
not selected while a normal matching static-roots binary is present. It remains
a probe for snapshots that fail in the opposite static-roots direction.

## Mistake analysis

I had enough evidence for one Electron 34.3.0 sample, but not enough structure
to prevent future version mixing. The fix is to make version matching executable
in the test gate: the script asks Electron for its V8 version and asks v8asm for
its V8 version, then only validates exact matches.

Generated `.jsc` test artifacts also appeared under
`tests/decomp_rounds/cases/`. They are now ignored as generated files so they do
not get mistaken for source fixtures or committed accidentally.
