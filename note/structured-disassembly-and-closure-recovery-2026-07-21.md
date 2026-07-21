# 从文本反汇编到结构化对象图：V8 cached data 反编译改进记录

## 背景

旧数据流先把 V8 cached data 打印成仿 `v8asm` 文本，再由 decompiler 用正则
重新解析。这个过程会丢失常量池归属、引用类型、SFI 与 BytecodeArray 的直接关系、
ScopeInfo 布局和跳转目标等信息，也使输出格式的小改动容易破坏反编译。

新的 Python disassembler 仍保留文本输出，但 decompiler 的主数据通路改为 schema
version 1 JSON。JSON 以稳定逻辑地址为 key，保存完整对象引用和显式关系。逻辑地址
只在一份离线文档内表示对象身份，不是 V8 进程中的真实 heap pointer；cached data
中的真实位置由 `file_offset`、`object_file_offset` 等字段单独保存。

## 结构化数据设计

顶层字段包括：

- `schema` 和 `schema_version`：consumer 必须校验；
- `metadata`：V8 版本、runtime variant、tagged size、cache header 和 snapshot 信息；
- `objects`：逻辑地址到对象记录的映射；
- `object_order`：确定性的遍历顺序。

BytecodeArray 保存 typed operands、格式化参数数组、raw bytes 和独立 jump target。
SharedFunctionInfo 直接链接 BytecodeArray 和 ScopeInfo。FixedArray、Array/Object
Boilerplate、String 和常量池元素均使用结构化 reference，不再依赖相邻文本区块。

详细字段见 `disassembler/SCHEMA.md`。

## 闭包和 context 恢复

decompiler 只在 `CreateClosure` 的常量项确实指向 SharedFunctionInfo 时建立父子关系，
因此不会仅凭函数名或输出文本猜测嵌套层级。匿名函数按对象顺序获得稳定唯一名称，
例如 `anonymous_1`、`anonymous_2`。

ScopeInfo 的以下数据都由对应 V8 tag 的官方源码生成 profile：

- ScopeType 枚举；
- context extension flag bit；
- normal/extended context header 长度；
- inlined local name 上限和 variable-part 布局。

反编译时把 local index 转换为真实 context slot，再沿 closure 父链查询名称。例如
`makeAdder` 中的 slot 2 可以恢复为 `base`，子函数的读取也直接显示 `base`。
默认参数产生的 BLOCK_SCOPE 同样参与查询，避免只处理 FUNCTION_SCOPE。

函数签名中的简单默认值通过真实控制流识别：参数读取、
`JumpIfNotUndefined` 的两个分支及其汇合点必须一致，默认分支还必须是可证明的
字面量加载。该逻辑不依赖函数名、固定 bytecode offset 或某个 V8 版本的 opcode
编号。

## 字面量对象

ObjectBoilerplateDescription 在大版本间有两种布局：10.x 的 FixedArray 旧布局，以及
新版本的 TaggedArrayBase 布局。两种布局均由源码生成到 profile。对于 build flag
导致 root map 名称偏移的旧版本，类型由 `CreateArrayLiteral`/`CreateObjectLiteral`
与常量池的实际引用关系确定，而不是补写固定 root index。

## 验证

验证覆盖：

- 26 个已有 V8 构建缓存通过 JSON 装载并进入 decompiler；
- 10.2.154.26、11.3.244.8、12.4.254.21、13.6.233.10 使用同一复杂 JS fixture；
- fixture 覆盖默认参数、嵌套 closure、对象方法、箭头函数、捕获变量、对象/数组
  字面量、`for...of`、optional chaining 和 nullish coalescing；
- 四个版本均恢复 6 个 BytecodeArray、唯一函数名、closure 嵌套、`value` 捕获变量，
  `arg0 = 0` / `arg0 = 1` 默认参数以及
  `{ enabled: true, value: 3 }` 等字面量内容；
- legacy 文本输入继续由兼容路径处理。

## 仍未解决

- 多层显式 context depth、slot shadowing 和定义 bytecode offset 仍需专门 IR；
- 没有匹配 snapshot 时，部分 read-only 字符串只能保持 unresolved；
- 参数名若未进入 ScopeInfo，cached data 本身通常没有足够信息恢复源码名称；
- level 4 仍有寄存器、TDZ 检查和少量 goto，需要继续做有证据的数据流恢复。
