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
