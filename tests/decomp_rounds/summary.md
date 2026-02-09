# Decompile Round Summary

| case | mode | accu_lines | reg_refs | goto_comments | raw_goto | holes |
|---|---:|---:|---:|---:|---:|---:|
| 01_arith | v8asm | 9 | 18 | 0 | 0 | 2 |
| 01_arith | bytenode | 8 | 17 | 0 | 0 | 2 |
| 02_if_else | v8asm | 10 | 9 | 0 | 0 | 2 |
| 02_if_else | bytenode | 8 | 8 | 0 | 0 | 2 |
| 03_for_of_sum | v8asm | 9 | 34 | 0 | 0 | 4 |
| 03_for_of_sum | bytenode | 7 | 32 | 0 | 0 | 4 |
| 04_nested_loop_if | v8asm | 26 | 66 | 1 | 1 | 7 |
| 04_nested_loop_if | bytenode | 24 | 64 | 1 | 1 | 7 |
| 05_object_calls | v8asm | 7 | 17 | 0 | 0 | 2 |
| 05_object_calls | bytenode | 5 | 19 | 0 | 0 | 2 |
| 06_closure | v8asm | 10 | 15 | 0 | 0 | 2 |
| 06_closure | bytenode | 6 | 17 | 0 | 0 | 2 |
| 07_try_catch | v8asm | 8 | 16 | 0 | 0 | 3 |
| 07_try_catch | bytenode | 0 | 0 | 0 | 0 | 0 |
| 08_switch | v8asm | 4 | 10 | 0 | 0 | 2 |
| 08_switch | bytenode | 2 | 9 | 0 | 0 | 2 |

## Quick Inspection Targets
- Prefer cases with highest `accu_lines` and `reg_refs` for next cleanups.
- Any non-zero `raw_goto` indicates structurer fallback/regression.
