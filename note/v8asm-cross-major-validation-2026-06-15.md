# v8asm cross-major validation notes, 2026-06-15

This note records the final validation pass for the cross-major V8 patch set.
All version switches used the official checkout flow from `start_env.md`:

```bash
cd /home/aynakeya/workspace/tmp/v8test
source start_env.md
cd v8
git checkout <tag>
gclient sync --with_branch_heads --with_tags
git apply --3way /home/aynakeya/workspace/v8asm/v8patch/<patch>
gn gen out/<versioned-output-dir>
autoninja -j10 -C out/<versioned-output-dir> v8asm
```

The existing `out/` directories were kept so V8 build artifacts could be reused.
During official `gclient sync`, depot_tools still triggered upstream landmines for
some versions and invalidated parts of the build tree. That was not manual cache
deletion.

## Patch compatibility matrix

| V8 tag | Patch | Build dir | Result |
| --- | --- | --- | --- |
| `10.2.154.26` | `v8patch/v8asm-10.2.patch` | `out/v8asm.10.2.node18.x64.release` | `v8asm version` -> `10.2.154.26` |
| `11.3.244.8` | `v8patch/v8asm-11.3.patch` | `out/v8asm.11.3.node20.x64.release` | `v8asm version` -> `11.3.244.8` |
| `11.9.169.7` | `v8patch/v8asm-11.9.patch` | `out/v8asm.11.9.x64.release` | `v8asm version` -> `11.9.169.7` |
| `12.4.254.21` | `v8patch/v8asm-12.4.patch` | `out/v8asm.12.4.node22.x64.release` | `v8asm version` -> `12.4.254.21` |
| `12.9.202.28` | `v8patch/v8asm-12.9.patch` | `out/v8asm.12.9.x64.release` | `v8asm version` -> `12.9.202.28` |
| `13.4.114.21` | `v8patch/v8asm-13.4.patch` | `out/v8asm.13.4.x64.release` | `v8asm version` -> `13.4.114.21` |
| `13.6.233.10` | `v8patch/v8asm.patch` | `out/v8asm.13.6.x64.release` | `v8asm version` -> `13.6.233.10` |

Every patch above was also checked from a clean detached worktree with plain:

```bash
git apply --3way --check <patch>
```

No `--recount` or manual conflict resolution is needed for the committed patch
files.

## Fixes synchronized in this pass

The field-level read-only-space short print diagnostics from the 13.x work were
backported to the older patch files. This replaces the broader print guard as the
first line of diagnosis: when a read-only heap object size cannot be decoded, the
output now includes page boundary details, a guarded header dump, and the field
offset being printed.

The 10.2 patch uses `OBJECT_POINTER_ALIGN(object_size)` in the read-only object
boundary helper. V8 10.2 does not provide `ALIGN_TO_ALLOCATION_ALIGNMENT`, which
caused the first 10.2 rebuild to fail.

The 12.4 and 12.9 patches use the local `bool snapshot_version_mismatch` variable
when calling `validate_snapshot_blob_version(...)`. Those V8 versions expect a
`bool*` mismatch output parameter, not the `force_incompatible` boolean directly.

The 12.4 and 12.9 patch files were regenerated from already compiled source
states after the signature fix. A final clean-worktree check confirmed both now
apply with plain `git apply --3way --check`.

## Atom/Electron context status

The 13.4 Electron/Atom recovery path remains the validated target for
`atom.compiled.dist.jsc`. With the provided context snapshot:

```bash
V8ASM=/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.13.4.x64.release/v8asm
SNAPSHOT=/home/aynakeya/workspace/v8asm/v8context/v8_context_snapshot.bin
JSC=/home/aynakeya/workspace/v8asm/atom.compiled.dist.jsc
DISASM=/tmp/atom.13.4.final.disasm.txt

$V8ASM --snapshot_blob "$SNAPSHOT" disasm "$JSC" --force-incompatible > "$DISASM"
python3 decompiler/v8decompiler.py "$DISASM" --level 4 --runtime \
  > note/atom.compiled.dist.decompiled.l4.js
```

the validation produced `note/atom.compiled.dist.decompiled.l4.js` with:

```text
functions=812
raw_goto=0
unknown_comments=0
undefined_fallbacks=0
decompiler_stderr_bytes=0
```

`disasm` stderr is non-empty by design in this forced Electron run. It contains
the expected snapshot suffix/version warnings plus cached-data `magic` and
`flags_hash` mismatch diagnostics; it does not contain a crash or DCHECK abort.

This pass did not add broader monkey patches. The cross-version patch set only
keeps the intended V8 header/snapshot compatibility hooks plus the diagnostic
short-print improvements.
