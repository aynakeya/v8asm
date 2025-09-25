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