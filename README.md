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
- level 4: level 3 + high-level pattern recovery (e.g. iterator state machine -> `for...of`, `+=` folding).

### regression rounds

```bash
./tests/decomp_rounds/run_round.sh
```

The round tests compile each case with local `v8asm` and bytenode, disassemble
both outputs, run the level-4 Python decompiler, and write
`tests/decomp_rounds/summary.md`. The summary tracks low-level residue
(`ACCU`, register refs, raw gotos), missing translator coverage (`unknown`), and
best-effort object-print placeholders (`undefined_fallbacks`). It also records
the exact `v8asm`, Node, Node V8, and bytenode versions used for that run.

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
bytenode cache against each `v8asm`. It skips `--force-incompatible` when the
Node V8 numeric version does not match the `v8asm` version, or when the Node
and `v8asm` pointer-compression build layout differs.

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

## v8 patch variants

- `v8patch/v8asm.patch`: current 13.6-oriented patch.
- `v8patch/v8asm-12.4.patch`: V8 12.4 adaptation. Node 22/bytenode needs a
  separate no-pointer-compression build of this branch.
- `v8patch/v8asm-12.9.patch`: V8 12.9 adaptation. It preserves the 12.x
  TrustedObject sandbox guard in `objects-printer.cc`.
- `v8patch/v8asm-11.9.patch`: V8 11.9 adaptation. It uses the 11.x
  `CodeSerializer::Deserialize(..., ScriptOriginOptions())` API and older
  object-cast helpers.

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
