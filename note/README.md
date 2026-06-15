# v8asm notes

This directory holds the research notes produced while adapting `v8asm` and the
Python decompiler across V8/Node/Electron versions.

- `electron-atom-jsc-v8-13-4-recovery-2026.md`: Atom/Electron 13.4 `.jsc`
  recovery notes and reproduction commands.
- `v8-bytecode-disassembly-research-2026.md`: broader V8 bytecode/decompiler
  research log.
- `v8asm-force-snapshot-and-node24-notes-2026.md`: snapshot forcing and
  Node/bytenode read-only-heap diagnostics.

Generated local artifacts:

- `atom.compiled.dist.decompiled.l4.js`: decompiled output for
  `atom.compiled.dist.jsc`, generated with
  `v8context/v8_context_snapshot.bin`.
- `atom.compiled.dist.checkversion.txt`: version/snapshot evidence for the same
  run.
