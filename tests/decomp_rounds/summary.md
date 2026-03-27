# Decompile Round Summary

| case | mode | accu_lines | reg_refs | goto_comments | raw_goto | holes |
|---|---:|---:|---:|---:|---:|---:|
| 01_arith | v8asm | 10 | 17 | 0 | 0 | 2 |
| 01_arith | bytenode | 8 | 17 | 0 | 0 | 2 |
| 02_if_else | v8asm | 6 | 8 | 0 | 0 | 2 |
| 02_if_else | bytenode | 4 | 8 | 0 | 0 | 2 |
| 03_for_of_sum | v8asm | 10 | 31 | 0 | 0 | 4 |
| 03_for_of_sum | bytenode | 8 | 31 | 0 | 0 | 4 |
| 04_nested_loop_if | v8asm | 10 | 40 | 0 | 0 | 6 |
| 04_nested_loop_if | bytenode | 8 | 40 | 0 | 0 | 6 |
| 05_object_calls | v8asm | 9 | 16 | 0 | 0 | 2 |
| 05_object_calls | bytenode | 7 | 18 | 0 | 0 | 2 |
| 06_closure | v8asm | 11 | 14 | 0 | 0 | 2 |
| 06_closure | bytenode | 7 | 17 | 0 | 0 | 2 |
| 07_try_catch | v8asm | 6 | 12 | 0 | 0 | 2 |
| 07_try_catch | bytenode | 0 | 0 | 0 | 0 | 0 |
| 08_switch | v8asm | 4 | 9 | 0 | 0 | 2 |
| 08_switch | bytenode | 2 | 9 | 0 | 0 | 2 |
| 09_all_features | v8asm | 58 | 106 | 0 | 0 | 6 |
| 09_all_features | bytenode | 0 | 0 | 0 | 0 | 0 |

## Quick Inspection Targets
- Prefer cases with highest `accu_lines` and `reg_refs` for next cleanups.
- Any non-zero `raw_goto` indicates structurer fallback/regression.
