# 未完成工作

这里只记录未完成的工作。已覆盖的行为见[语义 fixture](semantic-fixtures.md)，
验证范围见[验证方法](validation.md)，完成项不重复列出。

## 原则

- decompiler 只恢复可由 bytecode、对象图和控制流证明的 JavaScript 逻辑。
- 字符串解混淆、业务对象命名和代码用途判断属于独立 analyzer。
- 不为了减少寄存器、`ACCU` 或 `goto_comments` 而移动属性读取、调用或异常边界。
- 新规则必须先有失败 fixture，并同时验证成功模式和拒绝误匹配模式。
- profile、snapshot 或对象 layout 缺少证据时保持 `unresolved`。

## P0：继续核对表达式读写

后处理仍有较多文本规则。继续优化前，优先审查跨语句移动属性读取、二元运算求值顺序、
分支中的临时值存活，以及变量名与字符串/属性键的区分。新规则应消费可证明的读写信息；
不能把已有局部规则扩大为全局变量替换。必要时只为这些表达式引入小范围的结构化表示，
不一次重写整个 decompiler。

## P1：异常控制流的结构化与可读性

复杂 handler 当前保留显式基本块 dispatch。后续应把可证明的子图逐步恢复为嵌套
`try/finally`、循环和原生 `for-of`，不能只为了缩短输出删除 completion 状态。
尤其需要保留 IteratorClose、finalizer 覆盖返回/异常，以及穿过多层 finally 的跳转。
未识别的 generator/async 状态转换不在同步异常测试的保证范围内。

验收条件：

- 每种新增 lowering 都有原始 JavaScript 与恢复结果的可执行语义比较；
- 覆盖正常返回、抛出和 finalizer 副作用；
- 结构证据不完整时保留低层形式，不错误生成 `try` 语法。

## P1：扩大语义等价语料

当前语义门禁覆盖算术、短路、receiver/参数顺序、getter 副作用、闭包/context
shadowing、普通 catch 和 catch + finally。后续高风险改动应补充：

- for-of 的 iterator getter/return 抛错、continue 与嵌套迭代器关闭顺序；
- nullish assignment 的单次求值；
- 对象复制的 Proxy、不可枚举/继承属性及 getter 抛错；
- generator、async resume 和 reject 路径。

小型语义门禁随对应恢复规则补充；完整应用的探索性覆盖由 Taskboard 按需诊断，
不把尚未实现的功能加入 expectedFailure 来制造全绿结果。

## P1：扩展 class 元数据恢复

继续补继承与 `super`、计算键与数字键、匿名 class、字段、私有成员和静态初始化块。
大型 class 使用的 dictionary template、重复定义留下的未消费参数，也需要单独解析，
不能把当前 descriptor template 的支持扩大到这些布局。
Taskboard 中派生构造器和箭头函数的 lexical this 已触发非法 `this = ...` 输出，
完整文件因此无法执行。不能通过删掉赋值来掩盖尚未恢复的 receiver 初始化。
不合入外部 fork 的文本 class rewrite：不能删除真实方法名的数字后缀，也不能把
`super.value` 无条件转换为绑定方法。无法证明的 class 构造保留低层形式。

## P1：扩展作用域边界

继续验证 `with`、未解析外部 context、动态作用域及特殊函数类型的捕获行为。
合流后无法唯一确认的 context 必须保留低层表达；不得退回按 scope 列表顺序猜槽位。

## P1：从 V8 源码生成更完整的对象类型元数据

结构化 JSON 已记录稳定 `source.id`、`resolution` 和 `type_evidence`。当前可证明类型主要
来自 bytecode layout、literal operand、字符串布局和 root map；profile 还没有完整的
`InstanceType` 与 `ElementsKind` 元数据。

需要完成：

- 补全旧版 root/生成 map 的来源。已有 literal witness 时可以通过同一 map 恢复
  嵌套 boilerplate，但不能把这种局部证明扩展为整个旧版 root 表已经准确；

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

## P1：模板对象与 BigInt 常量

Taskboard 的 `codec` 仍包含未实现的 `GetTemplateObject`，需恢复 tagged template 的
raw/cooked 值、冻结/属性描述符和同一调用点的对象身份；不同调用点即使文本相同也
不能合并。非法 escape 的 cooked undefined 也要覆盖，不能只拼接成普通字符串。

该场景的 BigInt 字面量仍是 `<BigInt ...>` 占位符。下一步从源码生成其符号位和数字
布局，使用真实 cache 验证大整数、负值、零和运算，不用 Number 中转而损失精度。

## P1：实验性 undefined-double 构建形态

当前识别到了专用 NaN 位模式会明确报错。需要可确认的编译开关与真实 cache 后再
支持，不能仅因为版本源码包含该常量就推断目标构建启用了它。

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
- 运行相关测试；共享逻辑改动补多版本缓存回归，不每次都跑完整构建矩阵；
- 涉及 profile 时重新生成并审查全部 JSON diff；
- 对不支持的布局输出明确诊断，不猜 offset、类型或应用含义。
