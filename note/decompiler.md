# Python 反编译器

Python decompiler 的目标是把结构化 V8 bytecode 恢复成便于审计的 JavaScript 风格
伪代码。它优先保持语义和求值顺序；无法证明的结构保留低层表达，不为了可读性猜测。

## 使用方式

推荐输入为 disassembler 生成的结构化 JSON：

```bash
python3 -m disassembler input.jsc \
  --version <精确版本> \
  --snapshot-blob <匹配的-snapshot> \
  --format json > /tmp/input.disasm.json

python3 -m decompiler /tmp/input.disasm.json \
  > /tmp/input.decompiled.js
```

默认模式执行完整源码恢复。数字 `--level` 接口已经删除，也没有兼容映射；过去的
level 1、2、3 只是开发过程中的中间状态，不再构成公开能力。

需要逐条核对 bytecode 与 translator 输出时使用：

```bash
python3 -m decompiler /tmp/input.disasm.json --linear
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

这些测试使用 Node `vm` 和 `--runtime` 辅助函数，只证明覆盖到的语言子集。新增 rewrite
若可能移动调用、属性读取、异常边界或 context 访问，必须先增加能观察副作用的 fixture，
不能只比较输出文本。

## 恢复流程

当前处理管线分为五层：

1. 读取结构化对象图，建立 BytecodeArray、constant pool、SFI、ScopeInfo 和闭包关系；
2. 规范化已知的 V8 指令序列，去掉可证明冗余的临时形态；
3. 构建基本块和控制流，恢复条件、循环、switch、try/catch/finally 等结构；
4. 把 opcode 翻译成带寄存器和 `ACCU` 的保守伪代码；
5. 在函数内和文件级执行有边界的表达式、调用、对象、数组和闭包后处理。

仓库中仍有 `postprocess_level4*.py` 这类历史文件名。它们只是内部模块名，不表示 CLI
仍存在多个 level。

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

此时 `context_slot(...)`、`script_context[...]` 或 `ensureDefined(...)` 是有意保留的
低层证据，不应随意改名，更不能仅根据使用位置命名。

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

`raw_goto` 和未知 opcode 应默认保持为零。注释中的 goto 表示仍有可读性缺口，但不等同
于生成了可执行的非法 JavaScript 跳转。任何为“清零指标”而删除证据的 rewrite 都是
错误修复。

## Atom 当前效果

当前基准输入：

```text
JSC：example2/atom.compiled.dist.jsc
V8：13.4.114.21
snapshot：example2/v8_context_snapshot.bin
```

生成命令：

```bash
python3 -m disassembler example2/atom.compiled.dist.jsc \
  --version 13.4.114.21 \
  --snapshot-blob example2/v8_context_snapshot.bin \
  --format json > /tmp/atom.current.disasm.json

python3 -m decompiler /tmp/atom.current.disasm.json \
  > atom.compiled.dist.decompiled.current.js
```

2026-07-27 的这次输入产生 797 个 `BytecodeArray`，反编译输出 28,353 行、796 个
`function` 声明。质量扫描结果为：

```text
raw_goto：0
goto_comments：45
unknown_comments：0
undefined_fallbacks：0
```

这些数字只描述上述输入和日期，不是固定验收值。样本、profile 或恢复规则变化后应重新
运行分析脚本，不能继续引用旧的 794、809 或其他历史统计。

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
