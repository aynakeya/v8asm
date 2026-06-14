# Decompile Round Summary

## Round Environment
- v8asm_bin: `tests/decomp_rounds/bin_cache/v8asm.13.6.node24.x64.release/v8asm`
- v8asm_version: `13.6.233.10`
- v8asm_snapshot_blob: `tests/decomp_rounds/bin_cache/v8asm.13.6.node24.x64.release/snapshot_blob.bin`
- v8asm_build_args:
  - is_debug=false
  - v8_enable_object_print=true
  - v8_enable_disassembler=true
  - v8_enable_pointer_compression=false
- node_version: `v24.7.0`
- node_v8_version: `13.6.233.10-node.26`
- node_v8_enable_pointer_compression: `0`
- node_v8_enable_sandbox: `0`
- node_use_node_snapshot: `true`
- bytenode_path: `/home/aynakeya/.npm/_npx/ea56e60f3ac75570/node_modules/bytenode`
- bytenode_version: `1.5.7`
- compatibility_note: same numeric V8 version; Node/bytenode still use Node embedder snapshot/flags

| case | mode | status | header_mismatch | ro_snapshot | accu_lines | reg_refs | goto_comments | raw_goto | unknown | undefined_fallbacks | unresolved_objects | holes |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 01_arith | v8asm | ok | ok | ok | 0 | 10 | 0 | 0 | 0 | 0 | 0 | 2 |
| 01_arith | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 13 | 0 | 0 | 0 | 0 | 0 | 2 |
| 02_if_else | v8asm | ok | ok | ok | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 2 |
| 02_if_else | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 2 |
| 03_for_of_sum | v8asm | ok | ok | ok | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 2 |
| 03_for_of_sum | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 23 | 0 | 0 | 0 | 0 | 0 | 2 |
| 04_nested_loop_if | v8asm | ok | ok | ok | 0 | 30 | 0 | 0 | 0 | 0 | 0 | 2 |
| 04_nested_loop_if | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 33 | 0 | 0 | 0 | 0 | 0 | 2 |
| 05_object_calls | v8asm | ok | ok | ok | 0 | 8 | 0 | 0 | 0 | 0 | 0 | 2 |
| 05_object_calls | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 13 | 0 | 0 | 0 | 3 | 1 | 2 |
| 06_closure | v8asm | ok | ok | ok | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 2 |
| 06_closure | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 2 |
| 07_try_catch | v8asm | ok | ok | ok | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 2 |
| 07_try_catch | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 13 | 0 | 0 | 0 | 5 | 2 | 2 |
| 08_switch | v8asm | ok | ok | ok | 0 | 4 | 0 | 0 | 0 | 0 | 0 | 2 |
| 08_switch | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 7 | 0 | 0 | 0 | 0 | 0 | 2 |
| 09_all_features | v8asm | ok | ok | ok | 0 | 73 | 0 | 0 | 0 | 0 | 0 | 2 |
| 09_all_features | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 86 | 0 | 0 | 0 | 8 | 3 | 2 |
| 10_array_index | v8asm | ok | ok | ok | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 2 |
| 10_array_index | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 9 | 0 | 0 | 0 | 0 | 0 | 2 |
| 11_object_mutation | v8asm | ok | ok | ok | 0 | 3 | 0 | 0 | 0 | 0 | 0 | 2 |
| 11_object_mutation | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 6 | 0 | 0 | 0 | 6 | 1 | 2 |
| 12_logical_nullish | v8asm | ok | ok | ok | 0 | 9 | 0 | 0 | 0 | 0 | 0 | 2 |
| 12_logical_nullish | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 2 |
| 13_destructuring_spread | v8asm | ok | ok | ok | 0 | 37 | 0 | 0 | 0 | 0 | 0 | 2 |
| 13_destructuring_spread | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 48 | 0 | 0 | 0 | 3 | 1 | 2 |
| 14_optional_chaining | v8asm | ok | ok | ok | 0 | 12 | 0 | 0 | 0 | 0 | 0 | 2 |
| 14_optional_chaining | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 15 | 0 | 0 | 0 | 5 | 1 | 2 |
| 15_class_method | v8asm | ok | ok | ok | 0 | 19 | 0 | 0 | 0 | 0 | 0 | 3 |
| 15_class_method | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 25 | 0 | 0 | 0 | 0 | 0 | 3 |
| 16_regex_template | v8asm | ok | ok | ok | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 2 |
| 16_regex_template | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 27 | 0 | 0 | 0 | 3 | 1 | 2 |
| 17_async_await | v8asm | ok | ok | ok | 0 | 63 | 0 | 0 | 0 | 0 | 0 | 2 |
| 17_async_await | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 66 | 0 | 0 | 0 | 0 | 0 | 2 |
| 18_private_fields | v8asm | ok | ok | ok | 0 | 30 | 0 | 0 | 0 | 0 | 0 | 3 |
| 18_private_fields | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 34 | 0 | 0 | 0 | 0 | 0 | 3 |
| 19_generator_yield | v8asm | ok | ok | ok | 0 | 47 | 0 | 0 | 0 | 0 | 0 | 2 |
| 19_generator_yield | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 47 | 0 | 0 | 0 | 0 | 0 | 2 |
| 20_rest_spread_calls | v8asm | ok | ok | ok | 0 | 50 | 0 | 0 | 0 | 0 | 0 | 3 |
| 20_rest_spread_calls | bytenode | ok | magic,flags_hash,ro_snapshot | mismatch | 0 | 64 | 0 | 0 | 0 | 11 | 4 | 4 |

## Unresolved Read-Only Object Suffixes

| case | mode | suffixes |
|---|---:|---|
| 05_object_calls | bytenode | `de49` |
| 07_try_catch | bytenode | `e089,ee79` |
| 09_all_features | bytenode | `de49,e089,ee79` |
| 11_object_mutation | bytenode | `08e1` |
| 13_destructuring_spread | bytenode | `d321` |
| 14_optional_chaining | bytenode | `0919` |
| 16_regex_template | bytenode | `de49` |
| 20_rest_spread_calls | bytenode | `a701,d479,eed1,f0e1` |

## Quick Inspection Targets
- Prefer cases with highest `accu_lines` and `reg_refs` for next cleanups.
- Any non-zero `raw_goto` indicates structurer fallback/regression.
- Non-zero `unknown` usually means translator opcode coverage is missing.
- Non-zero `undefined_fallbacks` with `ro_snapshot=mismatch` points at V8/embedder snapshot object recovery, not Python translation.
- Non-zero `unresolved_objects` counts unique object-print failures in the disasm, before Python decompilation.
