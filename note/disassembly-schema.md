# 结构化反汇编 JSON

`uv run python -m disassembler INPUT --format json` 输出带版本的对象图。
decompiler 直接消费它，不重新解析人类可读的反汇编文本。字段采用 `under_score`。

## 顶层结构

```json
{
  "schema": "v8asm.disassembly",
  "schema_version": 1,
  "metadata": {
    "v8_version": "13.6.233.10",
    "root_layout_version": "13.6.233.10",
    "runtime_variant": "leaptiering",
    "literal_flags": {
      "define_keyed_set_function_name": 1,
      "define_keyed_dont_enum": 0,
      "object_literal_null_prototype": 16
    },
    "tagged_size": 4,
    "address_kind": "synthetic_serializer_object",
    "header": {}
  },
  "object_order": ["0xf00000000100"],
  "objects": {
    "0xf00000000100": {
      "address": "0xf00000000100",
      "type": "BytecodeArray",
      "type_evidence": { "kind": "bytecode_array_layout" },
      "provenance": {
        "kind": "serialized_object",
        "id": "serialized_object:1",
        "object_index": 1
      }
    }
  }
}
```

已有字段含义发生不兼容变更时递增 `schema_version`；新增可选字段不要求升级。
消费者必须拒绝未知 schema 或不支持的版本。

`metadata.v8_version` 是基础 profile 的数字版本，`metadata.root_layout_version` 是
实际选择的 root 元数据版本；后者可能为 `11.3.244.8-node.38` 等完整 embedder
版本。该字段描述解析器使用的布局，不是从 cache 自动识别出的 runtime 身份。

`metadata.literal_flags` 从所选 V8 tag 源码生成，描述计算属性命名、枚举属性和对象
字面量 prototype 的 flag 掩码。值可能跨版本变化，不得在 decompiler 中写死。
旧文档或文本输入没有此字段时，无法确定的 flag 保留显式低层调用，不猜测语义。

## 身份与引用

`objects` 的键是文档内稳定的逻辑地址，不是进程 heap pointer。真实输入位置使用
`file_offset`、`object_file_offset` 等独立字段。地址区间是实现细节，不能根据前缀
推断类型；消费者应跟随引用。`object_order` 按确定顺序恰好包含所有键一次。

Smi 表示为 `{"kind": "smi", "value": 3}`。引用示例：

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

- `address`：目标在文档中有身份时提供。
- `reference_kind`：保留 V8 如何编码该引用。
- `source.kind`：区分 serialized object、root、read-only heap、各类 object cache、
  attached reference 和 external reference。
- `source.id`：即使没有逻辑地址，也能在等价解析之间保持稳定。
- `resolution`：说明来自 payload、profile、匹配 snapshot、外部身份或仍未解析。
- `type_evidence`：说明类型判断的依据；map 名称必须有 profile/对象布局证据。

未知 cache/attached 引用保持 `unresolved`，不能猜 V8 instance type 或应用名称。

## 指令和词法关系

`BytecodeArray` 包含标量元数据、`constant_pool_address`、handler 条目和结构化指令。
指令记录 bytecode/file offset、原始字节、mnemonic、operand scale、有类型的原始
operand、translator 参数 token，以及存在时的明确 jump target。

`SharedFunctionInfo` 链接 `bytecode_address` 和可得的 `scope_info_address`。
可解码时，`ScopeInfo` 与其关联的 `SharedFunctionInfo` 同时输出 `function_kind`
（如 `NormalFunction`、`GetterFunction`、`ConciseMethod`）。枚举顺序和 flags 位布局
从对应 tag 的 `function-kind.h`、`scope-info.tq` 生成，不按函数名猜测；旧 JSON 缺少
该字段时 decompiler 不进行依赖函数类型的方法内联。
`ScopeInfo.context_locals` 使用精确 V8 源码生成的布局，同时记录 local index 和真实
context slot。`CreateClosure` 引用的 SFI 构成 decompiler 使用的词法函数树。

可解码的 local 还包含布尔字段 `needs_initialization`，来自 `VariableProperties.init_flag`；
有明确外层作用域时，`ScopeInfo.outer_scope_info` 保存标准 reference 记录。
尾部可选 PositionInfo、函数变量、推导函数名等字段共同决定外层引用的位置，不能使用
跨版本固定偏移。字段缺失或引用未解析不代表已经初始化，也不代表不存在外层作用域。

## Class 元数据

可识别的 `ClassBoilerplate` 包含：

- `arguments_count`：DefineClass 的参数数量；
- `argument_indices`：constructor、prototype、first_dynamic 的源码定义索引；
- `members`：真实 `key` 引用、`kind`（method/getter/setter）、`argument_index` 和 `static`；
- `supported`：当前 decoder 是否完整消费受支持 template 的动态参数。

字段布局来自对应 tag 的 `literal-objects.h`、`descriptor-array.tq`、`struct.tq` 和
`property-details.h`。旧版 ClassBoilerplate 继承 FixedArray，新版继承 Struct，不能
使用相同偏移；旧版依靠 DefineClass 操作数的常量来源确认 boilerplate 身份。
descriptor 的容量、有效条目数、属性 kind 和参数范围共同参与验证，不扫描任意对象
猜测成员。`supported=false` 不代表没有成员，只表示不能完整恢复为原生 class。

handler table 的位域从各 tag 的 `handler-table.h` 生成；JSON 中的 `handler` 已是
解码后的 bytecode offset，消费者无需再次移位。
