# 反汇编器与反编译器 TODO

本文只记录尚未完成的工作。已经通过聚焦测试和完整回归确认的 FixedArray、对象来源、
context slot 溯源、方法调用折叠和当前 `try/catch/finally` completion 恢复不再重复列出。

## 原则

- decompiler 只恢复可由 bytecode、对象图和控制流证明的 JavaScript 逻辑。
- 字符串解混淆、业务对象命名和代码用途判断属于独立 analyzer。
- 不为了减少寄存器、`ACCU` 或 `goto_comments` 而移动属性读取、调用或异常边界。
- 新规则必须先有失败 fixture，并同时验证成功模式和拒绝误匹配模式。
- profile、snapshot 或对象 layout 缺少证据时保持 `unresolved`。

## P1：扩展异常 completion 覆盖

当前实现已覆盖普通 `try/catch`，以及 return/throw 通过同一 finalizer dispatch 的
catch + finally 结构。尚未覆盖的 V8 lowering 需要由真实 fixture 驱动：

- 没有 catch 的 `try/finally`；
- try 或 catch 中的 `break`、`continue` 和多返回点；
- 多层 finally 和多个相邻 handler region；
- finalizer 自身包含分支、return 或 throw；
- 不同 V8 大版本使用的其他 completion token dispatch。

不要继续堆叠仅针对 offset 序列的局部正则。出现第二种实际 lowering 后，应先把 handler
table 建模成嵌套 region，再从 completion token、result register 和 dispatch target
恢复控制流。

验收条件：

- 每种新增 lowering 都有原始 JavaScript 与恢复结果的可执行语义比较；
- 覆盖正常返回、抛出和 finalizer 副作用；
- 结构证据不完整时保留低层形式，不错误生成 `try` 语法。

## P1：扩大语义等价语料

当前语义门禁覆盖算术、短路、receiver/参数顺序、getter 副作用、闭包/context
shadowing、普通 catch 和 catch + finally。后续高风险改动应补充：

- for-of 的 iterator close、break 和抛出路径；
- switch fallthrough；
- optional chaining 与 nullish assignment 的单次求值；
- object/array spread 的 getter 顺序；
- generator、async resume 和 reject 路径。

只在准备修改对应恢复规则时添加 fixture，不追求无目标的语法覆盖率。

## P1：从 V8 源码生成更完整的对象类型元数据

结构化 JSON 已记录稳定 `source.id`、`resolution` 和 `type_evidence`。当前可证明类型主要
来自 bytecode layout、literal operand、字符串布局和 root map；profile 还没有完整的
`InstanceType` 与 `ElementsKind` 元数据。

需要完成：

- 从每个精确 V8 tag 的官方源码生成 `InstanceType` 和 `ElementsKind` 名称；
- 明确区分 map 名称、推导的对象类型和真实 instance type；
- 只在 map 或对象 layout 能对应时填充类型；
- 为不同大版本添加生成器和真实 cache 测试，禁止手写一份跨版本枚举。

## P2：有边界的对象显示

底层对象图必须保持完整，文本或 JSON 展示可以有独立边界：

- 默认标记大型数组的省略范围；
- 支持按稳定 object ID 定向输出全部已解析元素；
- 循环引用只输出 reference，不递归复制；
- 畸形长度不能造成越界、无限递归或巨量输出。

显示截断不能改变 decompiler 消费的结构化对象图。

## P2：处理残留控制流诊断

当前真实语料没有未实现 opcode，但部分已恢复循环后仍保留 `// goto offset_N`。这些注释
没有可执行语义，却可能提示仍未结构化的异常边或 dispatch。

后续只能在 CFG 已证明输出下一节点就是 jump target、且不存在未消费 predecessor 时
删除。不能在字符串后处理阶段全局移除 `goto_comments`，否则会隐藏控制流缺口。

## P2：核对 `TestUndetectable`

当前输出 `isUndetectable(...)` 是保守的 V8 predicate 表达。只有从对应版本源码、
聚焦 bytecode fixture 和 JavaScript 可观察行为共同证明后，才决定是否换成更接近源码
的表达式。名称不直观本身不是语义 bug。

## 独立 analyzer 候选

以下工作不进入 fidelity decompiler：

- 识别 `array[index - constant]` 字符串 decoder；
- 模拟受限 `push`、`shift`、`splice` shuffle；
- 为 decoder 调用添加索引或明文注释；
- 根据属性、出现频率或调用位置猜测应用层对象名称；
- 判断代码实现了什么业务功能。

analyzer 可以消费结构化对象图或后续稳定 IR，但不能反向修改 decompiler 的忠实输出。

## 完成门槛

每项实现都必须：

- 修改前先稳定复现；
- 使用对应 V8 版本的真实 cache，涉及 snapshot 时要求 checksum 匹配；
- 添加可观察副作用或异常结果的语义测试；
- 运行完整 Python 测试；
- 涉及 profile 时重新生成并审查全部 JSON diff；
- 对不支持的布局输出明确诊断，不猜 offset、类型或应用含义。
