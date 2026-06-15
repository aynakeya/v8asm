from __future__ import annotations

from typing import List

from postprocess_level4_binary import (
    _compact_adjacent_binary_temp_registers,
    _compact_accu_binary_exprs,
    _compact_accu_compare_if,
    _compact_self_binary_assignments,
    _recover_accu_conditional_expr,
    _recover_accu_conditional_return_expr,
)
from postprocess_level4_arrays import _compact_fixed_array_builders, _compact_spread_array_builders
from postprocess_level4_calls import _rewrite_bound_method_calls
from postprocess_level4_cleanup import (
    _collapse_accu_store_return,
    _collapse_accu_store,
    _collapse_accu_push_context,
    _convert_unused_accu_assign_to_expr,
    _drop_duplicate_expr_before_assignment,
    _drop_unused_pure_reg_assignments,
    _drop_unused_pure_accu_loads,
    _flatten_else_after_early_exit,
    _inline_simple_accu_loads_into_next_line,
    _name_async_reject_handler_exceptions,
    _simplify_accu_throw,
    _simplify_accu_return,
)
from postprocess_level4_common import _compact_compound_assignments, _extract_indent
from postprocess_level4_forof import (
    _avoid_for_of_loop_var_source_collision,
    _recover_for_of,
    _strip_for_of_recovery_noise,
    _strip_for_of_state_initializers,
)
from postprocess_level4_defaults import recover_undefined_default_assignments
from postprocess_level4_generators import _inline_generator_resume_mode_switches
from postprocess_level4_guards import (
    _strip_iterator_exception_guard,
    _strip_pending_message_status_guard,
)
from postprocess_level4_inline import _inline_single_use_registers
from postprocess_level4_logical import (
    combine_nested_truthy_ifs,
    drop_redundant_empty_else_truthy_guards,
    inline_accu_equality_condition_loads,
    inline_accu_condition_loads,
    recover_nullish_assignments,
    recover_or_fallback_assignments,
    recover_or_fallback_returns,
    rewrite_accu_condition_after_duplicate_store,
    rewrite_accu_condition_after_reg_store,
)
from postprocess_level4_optional import recover_optional_chains
from postprocess_level4_properties import (
    _compact_accu_property_stores,
    _compact_keyed_property_reads,
)
from postprocess_level4_strings import _compact_string_concat_chains
from postprocess_level4_switch import (
    _recover_constant_dispatch_assignments,
    _recover_switch_assignments,
    _recover_two_case_switch,
)


def recover_js_structures(lines: List[str]) -> List[str]:
    current = _recover_for_of_until_stable(lines)
    current = _strip_iterator_exception_guard(current)
    current = _strip_pending_message_status_guard(current)
    current = _compact_spread_array_builders(current)
    current = _compact_keyed_property_reads(current)
    current = _compact_accu_property_stores(current)
    current = recover_optional_chains(current)
    current = recover_nullish_assignments(current)
    current = recover_undefined_default_assignments(current)
    current = recover_or_fallback_assignments(current)
    current = rewrite_accu_condition_after_duplicate_store(current)
    current = rewrite_accu_condition_after_reg_store(current)
    current = inline_accu_equality_condition_loads(current)
    current = inline_accu_condition_loads(current)
    current = recover_or_fallback_returns(current)
    current = combine_nested_truthy_ifs(current)
    current = _recover_switch_assignments(current)
    current = _inline_single_use_registers(current)
    current = _recover_accu_conditional_expr(current)
    current = _compact_string_concat_chains(current)
    current = _simplify_accu_return(current)
    current = _recover_accu_conditional_return_expr(current)
    current = _simplify_accu_throw(current)
    current = _flatten_else_after_early_exit(current)
    current = _recover_two_case_switch(current)
    current = _recover_constant_dispatch_assignments(current)
    current = _compact_accu_compare_if(current)
    current = _convert_unused_accu_assign_to_expr(current)
    current = inline_accu_equality_condition_loads(current)
    current = _rewrite_bound_method_calls(current)
    current = _compact_string_concat_chains(current)
    current = _drop_duplicate_expr_before_assignment(current)
    current = _collapse_accu_store(current)
    current = _collapse_accu_push_context(current)
    current = _collapse_accu_store_return(current)
    current = _compact_accu_binary_exprs(current)
    current = _compact_fixed_array_builders(current)
    current = _compact_adjacent_binary_temp_registers(current)
    current = _compact_self_binary_assignments(current)
    current = _rewrite_bound_method_calls(current)
    current = _inline_generator_resume_mode_switches(current)
    current = _strip_for_of_state_initializers(current)
    current = _strip_for_of_recovery_noise(current)
    current = _avoid_for_of_loop_var_source_collision(current)
    current = _drop_unused_pure_accu_loads(current)
    current = _name_async_reject_handler_exceptions(current)
    current = _inline_simple_accu_loads_into_next_line(current)
    current = _drop_unused_pure_accu_loads(current)
    current = _drop_unused_pure_reg_assignments(current)
    current = recover_or_fallback_returns(current)
    current = combine_nested_truthy_ifs(current)
    current = drop_redundant_empty_else_truthy_guards(current)
    current = _normalize_block_indentation(current)
    return current


def _recover_for_of_until_stable(lines: List[str]) -> List[str]:
    current = lines
    while True:
        nxt = _recover_for_of(current)
        if nxt == current:
            return current
        current = nxt


def _normalize_block_indentation(lines: List[str]) -> List[str]:
    nonempty = [line for line in lines if line.strip()]
    if not nonempty:
        return lines
    base = min(len(_extract_indent(line)) for line in nonempty)
    base_indent = " " * base
    depth = 0
    out: List[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue

        if stripped.startswith("}"):
            depth = max(0, depth - 1)

        out.append(f"{base_indent}{'  ' * depth}{stripped}")

        if stripped.endswith("{"):
            depth += 1

    return out
