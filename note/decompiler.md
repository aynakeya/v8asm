# Python 反编译器

Python decompiler 的目标是把结构化 V8 bytecode 恢复成便于审计的 JavaScript 风格
伪代码。它优先保持语义和求值顺序；无法证明的结构保留低层表达，不为了可读性猜测。

## 使用方式

推荐输入为 disassembler 生成的结构化 JSON：

```bash
uv run python -m disassembler input.jsc \
  --version <精确版本> \
  --snapshot-blob <匹配的-snapshot> \
  --format json > /tmp/input.disasm.json

uv run python -m decompiler /tmp/input.disasm.json \
  > /tmp/input.decompiled.js
```

默认模式执行完整源码恢复。数字 `--level` 接口已经删除，也没有兼容映射；过去的
level 1、2、3 只是开发过程中的中间状态，不再构成公开能力。

需要逐条核对 bytecode 与 translator 输出时使用：

```bash
uv run python -m decompiler /tmp/input.disasm.json --linear
```

`--linear` 是诊断模式，不做高层控制流和文件级后处理。`--runtime` 会附加一个轻量
JavaScript 辅助运行时，便于尝试执行伪代码，但不保证输出等价于可直接运行的原程序。

## 正确性门禁

`tests/test_semantic_equivalence.py` 会对同一个 fixture 分别执行原始 JavaScript 和
反编译结果，并比较正常返回值或异常结果。当前覆盖：

- 算术和短路求值；
- 方法 receiver、参数和 getter 的求值次数与顺序；
- 闭包状态、slot shadowing 和多层 context depth；
- 普通 `try/catch`；
- return、throw、catch 与 finally completion 的组合。
- 可选链的计算属性键、getter、可选方法调用与 nullish fallback 的执行顺序；
- 默认参数、rest/spread、`arguments.length` 和 unmapped arguments 与形参的独立性。
- 对象解构/rest/spread 的 getter 顺序、Symbol 保留/排除、计算属性转换和函数命名；
- `__proto__` 自有数据属性与真正的 null prototype 的区分。
- 闭包、寄存器局部与脚本级绑定的 TDZ，显式初始化为 `undefined` 的区别；
- `typeof` 未定义全局变量不抛错，但属性 getter 自己抛出的异常必须保留；
- Number/BigInt 的前后置自增自减、数值转换顺序、负零和复合赋值结果；
- 严格与非严格 `delete`，包括计算键、Symbol、不可配置属性和 Proxy trap。

这些测试使用 Node `vm` 和 `--runtime` 辅助函数，只证明覆盖到的语言子集。新增 rewrite
若可能移动调用、属性读取、异常边界或 context 访问，必须先增加能观察副作用的 fixture，
不能只比较输出文本。

特性清单、fixture 生成方法和待补项目见
[语义 fixture 说明](semantic-fixtures.md)。计算属性值同时存入寄存器与
ACCU 时必须复用已读取的值，不能重复调用 key 表达式或 getter。
`CreateUnmappedArguments` 使用严格模式 helper 创建真正的独立 arguments 对象，
不能简单替换为数组，也不能复用可能与形参联动的非严格模式 arguments。

## 外部代码

不合入 username1419/v8asm 的 class rewrite。后续 class 恢复应使用 SFI、属性元数据
和作用域证据，不能通过方法名后缀或文本位置猜测；属性读取与调用必须保持独立语义。

## 恢复流程

当前处理管线分为五层：

1. 读取结构化对象图，建立 BytecodeArray、constant pool、SFI、ScopeInfo 和闭包关系；
2. 规范化已知的 V8 指令序列，去掉可证明冗余的临时形态；
3. 构建基本块和控制流，恢复条件、循环、switch、try/catch/finally 等结构；
4. 把 opcode 翻译成带寄存器和 `ACCU` 的保守伪代码；
5. 在函数内和文件级执行有边界的表达式、调用、对象、数组和闭包后处理。

源码恢复规则统一放在 `decompiler/recovery/`，不再保留带数字 level 的内部模块或兼容入口：

- `propagation.py`：局部寄存器别名传播；
- `pipeline.py`：按顺序组合控制流、表达式和局部清理规则；
- `calls.py`、`objects.py`、`arrays.py` 等：各自负责一种可证明的指令形态；
- `expressions.py`：相邻 ACCU 表达式合并和死结果清理，保留调用与 getter 的副作用；
- `common.py`：共享标识符识别和局部存活检查；分支、未恢复的 jump/switch 是传播边界；
- `destructuring.py`：完整匹配 null 检查、逐项读取和 rest 排除列表；
- `literals.py`：在单个父函数内恢复对象、getter/setter 和计算属性方法；
- `file.py`：文件级名称整理，不负责跨函数拼接对象方法。

`core.py` 只编排对象读取、单函数恢复和函数树输出。恢复嵌套方法时传入该父函数实际的
子函数与类型信息，不在整个输出文件中搜索同名函数。默认输出不重复打印整份常量池，
只声明仍然使用的临时寄存器；`--linear` 保留逐指令诊断和常量池信息。

## 当前可恢复内容

在输入对象和控制流足够完整时，当前实现可以恢复或简化：

- 函数树、参数和可识别的函数名；
- 常量池字符串、Smi、FixedArray 和 literal boilerplate；
- 属性读取、赋值、常见调用和构造调用；
- if/else、短路表达式、循环、switch、try/catch/finally；
- 对象和数组字面量的常见构建序列；
- 模板字符串、字符串连接和部分默认参数；
- 部分 generator、for-of、optional-chain 和 compound assignment 形态；
- ScopeInfo 已知时的 context local 名称和嵌套闭包关系。

这些都是模式受限的语义恢复，不是通用 JavaScript 反编译证明。每个 rewrite 都应有
正向测试和拒绝误折叠的反向测试。

## 对象解构与复制

`CloneObject` 恢复为原生对象 spread；null-prototype 分支由 profile 中的 flag 决定。
不含 spread 的 `CreateObjectLiteral` 同样读取 null-prototype flag；共享空 boilerplate
自身的零 flag 不能覆盖指令的创建 flag。嵌套对象则读取各自 boilerplate 的 flag。
rest/copy helper 只复制自有、可枚举的字符串与 Symbol 属性，按原顺序读取 getter。
排除属性在读取其值之前过滤，目标用数据属性定义，避免 `__proto__` setter 改变原型。

`ToName` 根据真实 operand 形态区分旧版寄存器输出和新版 ACCU 输出，属性键转换交给
JavaScript 的计算属性语义。计算属性的函数命名和可枚举 flag 来自精确 V8 源码；
缺少 metadata 的文本输入保留低层调用，不根据大版本或方法名猜测。

完整匹配时可以直接输出原生 JavaScript，例如：

```javascript
r2 = {
  get alphaValue() { return mark(3); },
  [r0]: 7,
  ["__proto__"]: 13,
};
;({ [r3]: r4, [r1]: r5, ...r6 } = r2);
r7 = { ...r2, betaValue: mark(17), extraValue: 19 };
```

解构前的分号防止前一条表达式因 JavaScript 自动分号插入规则而变成函数调用。只有
排除键、求值顺序和临时值存活范围都匹配时才折叠；键仍有其他用途则保留 `ToName`。
对象构造不能跨越未知语句或对象逃逸，也不能重复求值键或 getter。
丢弃 ACCU 结果时也会处理独立表达式的语句边界，例如 `;({ ...r3 });`，避免与上一行
调用合并；结果没有被使用并不意味着可以删除调用、类型转换或 getter 的副作用。

`DefineNamedOwnProperty` / `DefineKeyedOwnProperty` 与普通属性赋值分开处理。前者
必须定义自有数据属性，不能错误触发原型链上的 setter；未能折叠时保留
`define_literal_property`。`["__proto__"]` 也不能输出为改变原型的 `__proto__: ...`。

getter/setter 和 concise method 的类型从 `ScopeInfo` 标志解码；位移、掩码和枚举
顺序均由所选 V8 tag 的源码生成。只内联该父函数内单次引用、没有递归或兄弟函数引用的
已知类型函数；普通函数不能为了外观改成不可构造的方法。缺失类型信息时不猜测。
方法恢复依据 FunctionKind，不要求属性键与生成的函数标识符相同，因此字符串键和
数字键不会退化成普通函数。不能内联的已知方法以独立的原生 method 值保留身份和
不可构造性，避免把 `new method(...)` 的异常路径改成成功构造。

计算属性 getter/setter 支持直接恢复为原生语法；键中包含调用等中间步骤、无法安全
合并时，保留 `DefineGetterPropertyUnchecked` / `DefineSetterPropertyUnchecked`
辅助调用。辅助实现只更新指定的访问器部分，保留另一半，且不跨越中间语句移动键转换。
普通数据属性覆盖访问器、重复成员及 spread 后的访问器也有执行对照。

`object-rest-spread` 的完整恢复结果可在没有 `--runtime` 的情况下直接执行，测试同时
检查其副作用和结果。这个结论只针对该已覆盖样例，不代表任意 `.jsc` 都能恢复成可执行
源码。临时变量的原始名字若已丢失，仍保留 `rN`，不根据用途编造名称。

这不表示所有对象相关指令、Proxy trap 或异常路径都已完成，具体覆盖见 fixture 清单。

## 方法调用折叠

V8 常把 JavaScript 方法调用拆成“取属性，再以 receiver 调用”：

```javascript
r1 = r0.isDestroyed
if (truthy(r1.call(r0))) {
```

当两行相邻、receiver 完全相同、临时寄存器没有复用，而且中间没有可能改变属性或
求值顺序的表达式时，可以恢复为：

```javascript
if (truthy(r0.isDestroyed())) {
```

该规则不只作用于 `truthy(...)`，也覆盖 return、赋值、短路表达式等已经明确列出的
安全上下文。以下情况必须保留 `.call(...)`：

- 调用 receiver 与取属性 receiver 不同；
- receiver 是重复求值可能有副作用的复杂表达式；
- 取属性和调用之间存在其他语句；
- 临时方法值在后面继续使用；
- rewrite 会重复执行调用或改变参数求值顺序；
- `.call` 本身就是用户代码需要保留的目标语义。

因此不能做全局字符串替换。优化条件由寄存器身份、邻接关系、使用次数和表达式纯度
共同约束。

## FixedArray 和字符串数组

decompiler 能消费结构化对象图中的 `FixedArray` 和 `TrustedFixedArray`，并把已解析
元素用于 constant pool、函数声明数组和 literal 恢复。对应 standalone 回归测试不
依赖原生 `v8asm` 输出。

profile 明确命名的 `EmptyFixedArray` 和 `EmptyObjectBoilerplateDescription` 会作为
已知空对象解码，而不是未解析的 root 占位符；这也支持 `{ submenu: [] }` 等嵌套字面量。
每次创建的 JS 数组仍是独立对象，不能把共享的 V8 boilerplate 当作共享的运行时数组。

但“数组对象已恢复”和“数组中每个字符串都可见”是两件事。元素若指向 read-only
snapshot，仍需给 disassembler 传入 checksum 匹配的 snapshot。若应用启动时还会对
字符串数组做 push/shift/splice shuffle，静态数组只是 shuffle 前状态，不能直接把
索引调用替换成最终明文。

字符串 decoder 识别、shuffle 模拟和业务含义标注不属于忠实 decompiler。它们应放在
独立 analyzer 中消费反编译 IR 或结构化对象图。decompiler 保留原始调用和数组访问，
不因函数形状像混淆器就替换字符串。

## Context 和闭包

结构化输入会把 `SharedFunctionInfo`、`BytecodeArray` 和 `ScopeInfo` 直接关联。decompiler
利用 `CreateClosure` 的 constant-pool 引用建立词法函数树，并用 profile 中的
ScopeInfo layout 解析已知 context local。

当前 context 模型会按显式 depth 建立逐层 ScopeInfo 对应，记录 slot 的定义函数、
bytecode offset 和捕获来源，并在函数头输出 `Captures`。同名 slot 由所属 scope 区分，
来源不唯一时保留稳定的 synthetic 名称。

仍无法保证恢复源码中的原始变量名：

- 名称可能未被 serializer 保存；
- 优化或混淆可能让多个值共享 slot；
- 外层 context 可能来自 snapshot 或未支持对象；
- 跨函数数据流不一定能在局部 CFG 中证明。

此时 `context_slot(...)`、`script_context[...]` 或 `checked_lexical(...)` 是有意保留的
低层证据，不应随意改名，更不能仅根据使用位置命名。

`ScopeInfo` 还提供变量的 `needs_initialization` 和 `outer_scope_info` 引用。位域和
可变尾部布局均从精确源码生成；旧版可选 PositionInfo 与新版固定头部不能混用。
没有 `CreateClosure` 父边的全局函数可以沿明确的外层引用解析脚本绑定，但不能因此
把它改成嵌套函数声明。

未初始化的 lexical binding 保持 `HOLE`，读取时由
`checked_lexical(value, name)` 检查实际值并抛出 ReferenceError。
不能仅因为 slot 名称与检查字符串相同就删除 TDZ 检查，也不能把 `HOLE` 当成
`undefined`。只有简单函数入口初始化已被证明时才省略冗余检查。
旧 JSON 未提供脚本变量初始化状态时保留 `unresolved_initialization`，不猜默认值。

全局 `typeof` 必须保留对 Reference 的特殊处理：相邻的
`LdaGlobalInsideTypeof` 与 `TypeOf` / `TestTypeOf` 只有在单入口且不跨 handler 边界时
才合并。普通 jump、switch 常量表和 generator dispatch 都参与入口检查；不通过
捕获 ReferenceError 模拟，因为这会误吞用户 getter 抛出的异常。

目前的 context 模型仍不是逐指令的作用域状态机。多个 block/catch scope、循环每轮
重新绑定和 `PushContext` / `PopContext` 分支合流尚需专门验证，不能把已有闭包 fixture
的通过扩大解释成任意作用域结构都正确。

## 数值与删除

`ToNumeric` 不能替换为 `Number`：它保留 BigInt，并且只执行一次对象到原始值转换。
当前 helper 按 number hint 处理 `Symbol.toPrimitive`，否则依次尝试 `valueOf` 和
`toString`；`Inc` / `Dec` 使用原生 `++` / `--`，不能替换为可能拼接字符串的 `+ 1`，
也不能给 BigInt 加 Number 类型的 `1`。

表达式合并必须同时保留更新后的 ACCU 和赋值目标。临时结果仍被使用时不删除；
复合赋值使缓存的别名失效，不能把 `ACCU += 2` 的左值替换成之前读入的寄存器或常量。

`DeleteProperty*` 的 register operand 是对象，ACCU 是属性键。非严格模式恢复为
原生 `delete`；严格模式通过 `delete_property_strict` 保留删除失败时的 TypeError，
不能使用会改变原始值对象处理方式的 `Reflect.deleteProperty` 直接替代。

## 异常控制流

handler table 是恢复异常语义的唯一入口，不能把 handler 区段当普通线性代码。当前实现
支持普通 `try/catch`，以及满足完整证据链的 catch + finally completion：

- 外层 handler 覆盖内层 catch 区域；
- exception、completion token、pending message 和 result register 能对应；
- 正常与 catch 路径都保存 return completion 后跳入同一 finalizer；
- 尾部存在匹配的 rethrow/return dispatch。

只有整套结构匹配时才输出 `try/catch/finally`。若外层在内层 try 前还有可能抛出的有效
语句，则保留嵌套结构，避免把这些异常错误地交给 catch。

## 控制流与安全边界

默认源码恢复失败时，单个函数会回退到 linear 形式并保留诊断注释，不应让整个文件
丢失。判断输出质量时重点检查：

```text
raw_goto            实际可执行的 goto offset_... 语句
goto_comments        注释中的未结构化跳转
unknown_comments     未识别 opcode 注释
undefined_fallbacks  对象打印失败占位符
```

未知 opcode 明确输出 `WARNING: unsupported bytecode <名称> <操作数> @<偏移>`，
不能用没有 opcode 名称的 structured instruction 注释掩盖。语义 fixture 出现 WARNING
即失败，即使最终 JSON 恰好相同也不算通过。

`raw_goto` 和未知 opcode 应默认保持为零。注释中的 goto 表示仍有可读性缺口，但不等同
于生成了可执行的非法 JavaScript 跳转。任何为“清零指标”而删除证据的 rewrite 都是
错误修复。

## Atom 示例

本地示例输入（不随仓库分发）：

```text
JSC：example2/atom.compiled.dist.jsc
V8：13.4.114.21
snapshot：example2/v8_context_snapshot.bin
```

生成命令：

```bash
uv run python -m disassembler example2/atom.compiled.dist.jsc \
  --version 13.4.114.21 \
  --snapshot-blob example2/v8_context_snapshot.bin \
  --format json > /tmp/atom.current.disasm.json

uv run python -m decompiler /tmp/atom.current.disasm.json \
  > atom.compiled.dist.decompiled.current.js
```

该样例用于人工检查真实输入效果，不代替可执行语义 fixture。每次需要评价效果时，
重新记录输入、版本、命令和结果；不把历史行数或未知指令计数作为当前正确性的证明。

## 改进优先级

优先处理会导致语义错误、对象丢失或整函数回退的问题：

1. 错误 opcode、operand、jump target 或 constant-pool 解析；
2. FixedArray、SFI、ScopeInfo 等结构化对象缺失；
3. 控制流重建改变分支、异常或循环语义；
4. rewrite 重复副作用、改变 receiver 或调用参数顺序；
5. 大量函数回退 linear，或出现未知 opcode。

可读性优化必须建立在可证明模式上。以下内容不应优先做成猜测性全局规则：

- 根据属性使用位置猜对象真实名称；
- 未模拟 runtime shuffle 就替换混淆字符串；
- 仅为减少寄存器数量跨基本块传播表达式；
- 试图把所有 V8 internal predicate 强行翻译成源码语法；
- 为兼容已经删除的数字 level 保留额外分支。
