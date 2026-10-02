"""Recover base classes from DefineClass argument and boilerplate metadata."""

import json
import re

from ..objects import V8Address, V8ClassBoilerplate, V8SharedFunctionInfo, V8String
from ..utils import parse_jump_target


def recover_classes(context, bytecode, translator, instructions, nested_functions):
    if not any(item.mnemonic == "CallRuntime" and item.args[0] == "[DefineClass]" for item in instructions):
        return nested_functions, {}
    definitions = {}
    for source in nested_functions:
        match = re.match(r"function ([\w$]+)\((.*)\) \{", source)
        if match:
            definitions[match[1]] = (match[2], source.splitlines()[1:-1])
    registers = {}
    origins = {}
    accumulator = None
    accumulator_origin = set()
    consumed = set()
    expansions = {}
    strings = [obj.value for obj in context.objects if isinstance(obj, V8String)]
    boundaries = {parse_jump_target(item) for item in instructions}
    for item in instructions:
        if item.offset in boundaries:
            registers.clear()
            origins.clear()
            accumulator = None
        op, args = item.mnemonic, item.args
        if op in {"LdaConstant", "CreateClosure"}:
            accumulator = context.constant_object_for_instruction(bytecode, item)
            accumulator_origin = {item.offset}
        elif op == "LdaTheHole":
            accumulator = "HOLE"
            accumulator_origin = {item.offset}
        elif op == "Ldar":
            accumulator = registers.get(args[0])
            accumulator_origin = origins.get(args[0], set()) | {item.offset}
        elif op == "Star" or (op.startswith("Star") and op[4:].isdigit()):
            register = args[0] if op == "Star" else f"r{op[4:]}"
            registers[register] = accumulator
            origins[register] = accumulator_origin | {item.offset}
        elif op == "Mov":
            registers[args[1]] = registers.get(args[0])
            origins[args[1]] = origins.get(args[0], set()) | {item.offset}
        elif op == "CallRuntime" and args[0] == "[DefineClass]":
            arguments = translator._expand_range(args[1])
            boilerplate = registers.get(arguments[0])
            rendered = _render_class(context, boilerplate, arguments, registers, definitions)
            if rendered is not None:
                text, functions, aliases = rendered
                marker_name = f"__v8_class_{bytecode.address:x}_{item.offset}"
                while any(marker_name in value for value in strings):
                    marker_name += "_"
                marker = marker_name + "()"
                expansions[marker] = "(" + text + ")"
                for argument in arguments:
                    for offset in origins.get(argument, ()):
                        translator.overrides[offset] = ""
                constructor_register = arguments[boilerplate.argument_indices["constructor"]]
                translator.overrides[item.offset] = "\n".join([
                    f"{constructor_register} = {marker}",
                    *(f"{alias} = {constructor_register}" for alias in aliases if alias != constructor_register),
                    f"ACCU = {constructor_register}.prototype",
                ])
                consumed.update(functions)
            accumulator = None
        else:
            # Class arguments are produced in one straight-line initialization.
            registers.clear()
            origins.clear()
            accumulator = None
    if not consumed:
        return nested_functions, expansions
    for item in instructions:
        if item.mnemonic == "CreateClosure" and item.offset not in translator.overrides:
            function = context.constant_object_for_instruction(bytecode, item)
            if isinstance(function, V8SharedFunctionInfo):
                consumed.discard(context.get_function_name(function))
    return ([source for source in nested_functions
             if not any(source.startswith(f"function {name}(") for name in consumed)], expansions)


def _render_class(context, boilerplate, arguments, registers, definitions):
    if not isinstance(boilerplate, V8ClassBoilerplate) or not boilerplate.supported:
        return None
    if len(arguments) != boilerplate.arguments_count:
        return None
    indices = boilerplate.argument_indices
    constructor = registers.get(arguments[indices["constructor"]])
    if (not isinstance(constructor, V8SharedFunctionInfo)
        or constructor.func_kind not in {"BaseConstructor", "DefaultBaseConstructor"}
        or registers.get(arguments[indices["prototype"]]) != "HOLE"):
        return None
    name = context.get_function_name(constructor)
    if name not in definitions:
        return None
    params, body = definitions[name]
    # A class expression supplies strict-mode and non-callable constructor semantics.
    class_name = constructor.name_value
    if not class_name or not re.fullmatch(r"[A-Za-z_$][\w$]*", class_name):
        return None
    lines = [f"class {class_name} {{", f"  constructor({params}) {{",
             *("  " + line for line in body), "  }"]
    functions = {name}
    scopes = context.closure_scope_variables(context.get_object(constructor.trusted_function_data.address))
    for member in boilerplate.members:
        key = member["key"]
        key = context.get_object(key.address) if isinstance(key, V8Address) else None
        function = registers.get(arguments[member["argument_index"]])
        if not isinstance(key, V8String) or not isinstance(function, V8SharedFunctionInfo):
            return None
        function_name = context.get_function_name(function)
        if function_name not in definitions:
            return None
        params, body = definitions[function_name]
        kind = member["kind"]
        expected = {"method": "ConciseMethod", "getter": "GetterFunction", "setter": "SetterFunction"}[kind]
        if member["static"]:
            expected = "Static" + expected
        if function.func_kind != expected:
            return None
        prefix = "static " if member["static"] else ""
        prefix += {"method": "", "getter": "get ", "setter": "set "}[kind]
        # Quoted keys also preserve names such as __proto__ and reserved words.
        lines.extend([f"  {prefix}[{json.dumps(key.value)}]({params}) {{",
                      *("  " + line for line in body), "  }"])
        functions.add(function_name)
        for scope in context.closure_scope_variables(context.get_object(function.trusted_function_data.address)):
            if scope not in scopes:
                scopes.append(scope)
    lines.append("}")
    aliases = [register for register, value in registers.items() if value is constructor]
    expression = "\n".join(lines)
    if scopes:
        expression = f"(({', '.join(scopes)}) => {expression})({', '.join(scopes)})"
    return expression, functions, aliases
