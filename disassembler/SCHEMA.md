# Structured disassembly schema

`python3 -m disassembler INPUT --format json` emits a versioned object graph.
The decompiler consumes this graph directly and does not parse the text
listing.

## Document shape

```json
{
  "schema": "v8asm.disassembly",
  "schema_version": 1,
  "metadata": {
    "v8_version": "13.6.233.10",
    "runtime_variant": "leaptiering",
    "tagged_size": 4,
    "address_kind": "synthetic_serializer_object",
    "header": {}
  },
  "object_order": ["0xf00000000100"],
  "objects": {
    "0xf00000000100": {
      "address": "0xf00000000100",
      "type": "BytecodeArray",
      "type_evidence": {
        "kind": "bytecode_array_layout"
      },
      "provenance": {
        "kind": "serialized_object",
        "id": "serialized_object:1",
        "object_index": 1
      }
    }
  }
}
```

`schema_version` changes when an existing field changes meaning or becomes
incompatible. New optional fields may be added without changing version 1.
Consumers must reject unknown schema names and unsupported versions.

## Object identities

Every `objects` key is a stable logical address within one document. It is not
a V8 heap pointer and must not be used to access process memory. Actual cached
file positions are separate integer fields such as `file_offset` and
`object_file_offset`.

The current encoder uses disjoint logical ranges for serializer objects,
read-only/root references, and synthetic constant pools. These ranges are an
implementation detail. Consumers must follow address fields and treat the key
as opaque instead of deriving object kinds from its numeric prefix.

`object_order` contains every object key exactly once. It preserves the
deterministic rendering order while `objects` provides direct lookup.

## References and values

Small integers use:

```json
{"kind": "smi", "value": 3}
```

Object, root, and read-only references use:

```json
{
  "kind": "reference",
  "reference_kind": "object",
  "source": {
    "kind": "serialized_object",
    "id": "serialized_object:18",
    "object_index": 18
  },
  "resolution": "serialized_object",
  "address": "0xf00000001200",
  "object_index": 18,
  "target_type": "String",
  "type_evidence": {
    "kind": "serialized_string_layout",
    "map_name": "SeqOneByteStringMap"
  },
  "description": "<String>"
}
```

`address` is present when the target has a document identity. `reference_kind`
preserves how V8 encoded the reference. `source.kind` distinguishes serializer
objects, roots, read-only heap objects, startup/read-only/shared object caches,
attached references, and external references. `source.id` is stable within
equivalent parses even when the source has no synthetic address.

`resolution` records whether the target was resolved from a serialized object,
profile metadata, a matching read-only snapshot, or only an external identity.
`type_evidence.kind` states why a type was assigned. A root map name is included
only when the checked-in profile proves it. Unknown cache or attached targets
remain `unresolved`; the disassembler does not invent a V8 instance type or an
application-level name.

## Bytecode arrays

A `BytecodeArray` record contains scalar metadata, an explicit
`constant_pool_address`, handler entries, and structured instructions. Each
instruction includes:

- bytecode and file offsets;
- raw bytes;
- mnemonic and operand scale;
- typed raw operands (`kind` and integer `value`);
- formatted argument tokens used by the current translator;
- an explicit jump target when applicable.

The decompiler uses the argument array and jump target directly. The formatted
text listing remains available for humans and backwards compatibility, but is
not part of the structured decompiler path.

## Function and scope relationships

`SharedFunctionInfo` records link directly to `bytecode_address` and, when
available, `scope_info_address`. `ScopeInfo.context_locals` records both local
indexes and real context slots using layout data generated from the matching V8
source tag. Constant-pool `SharedFunctionInfo` references used by
`CreateClosure` form the lexical function tree used by the decompiler.
