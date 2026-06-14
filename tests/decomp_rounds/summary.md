# Decompile Round Summary

## Round Environment
- v8asm_bin: `/home/aynakeya/workspace/v8asm/v8asm`
- v8asm_version: `13.6.233.10`
- v8asm_build_args:
  - is_debug=false
  - v8_enable_object_print=true
  - v8_enable_disassembler=true
  - v8_enable_pointer_compression=false
- node_version: `v24.7.0`
- node_v8_version: `13.6.233.10-node.26`
- bytenode_path: `/home/aynakeya/.npm/_npx/ea56e60f3ac75570/node_modules/bytenode`
- bytenode_version: `1.5.7`
- compatibility_note: same numeric V8 version; Node/bytenode still use Node embedder snapshot/flags

| case | mode | header_mismatch | ro_snapshot | accu_lines | reg_refs | goto_comments | raw_goto | unknown | undefined_fallbacks | holes |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 01_arith | v8asm | ok | ok | 0 | 16 | 0 | 0 | 0 | 0 | 2 |
| 01_arith | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 16 | 0 | 0 | 0 | 0 | 2 |
| 02_if_else | v8asm | ok | ok | 0 | 7 | 0 | 0 | 0 | 0 | 2 |
| 02_if_else | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 7 | 0 | 0 | 0 | 0 | 2 |
| 03_for_of_sum | v8asm | ok | ok | 0 | 24 | 0 | 0 | 0 | 0 | 2 |
| 03_for_of_sum | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 24 | 0 | 0 | 0 | 0 | 2 |
| 04_nested_loop_if | v8asm | ok | ok | 0 | 34 | 0 | 0 | 0 | 0 | 2 |
| 04_nested_loop_if | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 34 | 0 | 0 | 0 | 0 | 2 |
| 05_object_calls | v8asm | ok | ok | 0 | 13 | 0 | 0 | 0 | 0 | 2 |
| 05_object_calls | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 15 | 0 | 0 | 0 | 3 | 2 |
| 06_closure | v8asm | ok | ok | 0 | 13 | 0 | 0 | 0 | 0 | 2 |
| 06_closure | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 15 | 0 | 0 | 0 | 0 | 2 |
| 07_try_catch | v8asm | ok | ok | 0 | 10 | 0 | 0 | 0 | 0 | 2 |
| 07_try_catch | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 14 | 0 | 0 | 0 | 5 | 2 |
| 08_switch | v8asm | ok | ok | 0 | 8 | 0 | 0 | 0 | 0 | 2 |
| 08_switch | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 8 | 0 | 0 | 0 | 0 | 2 |
| 09_all_features | v8asm | ok | ok | 0 | 89 | 0 | 0 | 0 | 0 | 2 |
| 09_all_features | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 96 | 0 | 0 | 0 | 8 | 2 |
| 10_array_index | v8asm | ok | ok | 0 | 11 | 0 | 0 | 0 | 0 | 2 |
| 10_array_index | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 11 | 0 | 0 | 0 | 0 | 2 |
| 11_object_mutation | v8asm | ok | ok | 0 | 7 | 0 | 0 | 0 | 0 | 2 |
| 11_object_mutation | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 7 | 0 | 0 | 0 | 7 | 2 |
| 12_logical_nullish | v8asm | ok | ok | 0 | 15 | 0 | 0 | 0 | 0 | 2 |
| 12_logical_nullish | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 15 | 0 | 0 | 0 | 0 | 2 |
| 13_destructuring_spread | v8asm | ok | ok | 0 | 42 | 0 | 0 | 0 | 0 | 2 |
| 13_destructuring_spread | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 52 | 0 | 0 | 0 | 3 | 2 |
| 14_optional_chaining | v8asm | ok | ok | 0 | 16 | 0 | 0 | 0 | 0 | 2 |
| 14_optional_chaining | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 16 | 0 | 0 | 0 | 6 | 2 |
| 15_class_method | v8asm | ok | ok | 0 | 28 | 0 | 0 | 0 | 0 | 4 |
| 15_class_method | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 33 | 0 | 0 | 0 | 0 | 4 |
| 16_regex_template | v8asm | ok | ok | 0 | 29 | 0 | 0 | 0 | 0 | 2 |
| 16_regex_template | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 31 | 0 | 0 | 0 | 3 | 2 |
| 17_async_await | v8asm | ok | ok | 0 | 85 | 0 | 0 | 0 | 0 | 2 |
| 17_async_await | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 85 | 0 | 0 | 0 | 0 | 2 |
| 18_private_fields | v8asm | ok | ok | 0 | 43 | 0 | 0 | 0 | 0 | 4 |
| 18_private_fields | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 48 | 0 | 0 | 0 | 0 | 4 |
| 19_generator_yield | v8asm | ok | ok | 0 | 63 | 0 | 0 | 0 | 0 | 2 |
| 19_generator_yield | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 54 | 0 | 0 | 0 | 0 | 2 |
| 20_rest_spread_calls | v8asm | ok | ok | 0 | 81 | 0 | 0 | 0 | 0 | 4 |
| 20_rest_spread_calls | bytenode | magic,flags_hash,ro_snapshot | mismatch | 0 | 90 | 0 | 0 | 0 | 12 | 5 |

## Quick Inspection Targets
- Prefer cases with highest `accu_lines` and `reg_refs` for next cleanups.
- Any non-zero `raw_goto` indicates structurer fallback/regression.
- Non-zero `unknown` usually means translator opcode coverage is missing.
- Non-zero `undefined_fallbacks` with `ro_snapshot=mismatch` points at V8/embedder snapshot object recovery, not Python translation.
