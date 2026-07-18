# 反汇编器与反编译器 TODO

本文只记录尚未完成的工作。现象、已验证事实和推测必须分开；不能把旧版
`v8asm` 的输出当成正确性标准，也不能根据对象出现频率猜测其业务含义。

## 总体优先级

1. 标记未解析对象的来源，并在有证据时输出 V8 类型。
2. 利用已恢复的数组和字符串，识别范围明确的字符串解码器调用。
3. 跟踪闭包 context slot 的定义和跨函数传递。
4. 为大型对象提供有边界的显示控制。
5. 最后处理有限 shuffle 模拟和 `isUndetectable` 表达。

## 实施决策

| 顺序 | 工作 | 决策 | 原因 |
| --- | --- | --- | --- |
| 1 | 未解析对象的来源和 V8 类型 | P1 | 稳定的身份和类型是继续解析对象字段的前提。 |
| 2 | 常量字符串解码器调用 | P1 | 数组内容已经可用，但仍需证明 decoder、索引和顺序。 |
| 3 | 闭包 context slot 溯源 | P1 | 能明显改善数据流，但不阻塞正确反汇编。 |
| 4 | 有边界的对象显示控制 | P2 | 输出策略应建立在稳定对象模型之上。 |
| 5 | 数组 shuffle 模拟 | P2，仅支持严格受限模式 | 通用方案会演变为不可靠的 JavaScript 求值器。 |
| 6 | `isUndetectable` 表达 | P2，先验证语义 | 仅凭 helper 名称不能证明当前翻译错误。 |

## 实施边界

以下方案不在当前实现范围内：

- **接受不匹配的 startup snapshot：** 离线解析应使用 checksum 匹配的
  snapshot，不能绕过校验后假定对象内容仍然正确。
- **递归展开所有 V8 堆对象：** 只处理从 code cache 常量可达且已有 profile
  布局支持的对象，不实现通用 V8 heap inspector。
- **为未解析对象猜测应用层名称：** 只能输出来源、instance type 和有证据的
  字段，不能根据出现次数推测业务身份。
- **解析 `globalThis` 的全部属性：** attached object 或运行时创建的状态不一定
  存在于 cached data 中；需要时应单独捕获运行时状态。
- **执行任意混淆器代码：** 不在反编译器中执行恢复出的 JavaScript。
- **无限制递归展开：** 输出必须保留循环检测和大小上限。
- **证据不足时替换 decoder 调用：** 任一前提未知时保留原始表达式。
- **仅因名称把 `isUndetectable` 当成缺陷：** 必须先核对 opcode 和 translator
  路径。

## 反汇编器

### P1：为未解析对象输出可用的身份信息

输出中仍可能出现 `<object_N>`，其来源可能是 code-cache object graph、
attached object、root、read-only snapshot object 或其他 cache。必须先区分
来源，才能决定是否可以解析内容。

需要完成：

- 为 placeholder 标记来源：cache object、root、attached reference、
  read-only snapshot object 或其他已知 cache。
- map 可解析时，输出对应 V8 instance type。
- 使用匹配 snapshot 时，解析 profile 已支持的 read-only object 和字符串。
- 只有 profile 包含对应 object layout 元数据时，才解析 map descriptor 和属性名。
- 无法解析时保留稳定的 object ID，并输出具体诊断。

验收条件：

- 可以从 constant-pool entry 跟踪到稳定的对象记录。
- 对象身份没有证据时必须保持 unresolved，不附加猜测的应用层名称。
- snapshot 不匹配时给出明确错误。
- 测试覆盖 cache、root、attached 和 read-only 四类引用。

### P2：改进对象类型和大型对象的显示

当前 `ArrayBoilerplateDescription` 的 elements kind 仍显示为数值，对象区段也
没有统一显示 map/type 信息。大型或深层对象默认还需要有边界的表示。

需要完成：

- 从对应 V8 profile 生成 `ElementsKind` 名称，不能把当前版本枚举手写进解析器。
- 对已解析对象统一显示有证据的 map 名称和 instance type。
- 默认限制大型对象的显示量，并明确标记省略范围。
- 支持按 object ID 定向输出所有已解析元素。
- 循环引用显示为 object reference，不重复递归。

验收条件：

- 不同 V8 大版本使用各自 profile 中的枚举和类型信息。
- 显示截断不改变底层解析结果。
- 定向展开能输出指定对象的全部已解析元素。
- 畸形长度和循环引用不会造成越界或无限递归。

## 反编译器

### P1：解析常见字符串解码器调用

数组和字符串内容已经可以进入 decompiler object model，但类似 `r0(2791)` 的
调用尚未被建模为字符串索引 decoder。

目标模式示例：

```javascript
function a0_0x5560(arg0, arg1) {
  arg0 = arg0 - 114;
  return _0x159d4f[arg0];
}
```

需要完成：

- 从 decompiler IR 动态识别范围明确的 `array[index - constant]` 模式。
- 识别结果先输出索引注释，例如
  `r0(2791) /* _0x159d4f[2677] */`。
- 只有 decoder target、offset、数组顺序和参数都可证明为常量时，才折叠为字符串
  字面量。
- 任一前提未知时保留原始表达式。

验收条件：

- 示例调用能够标注索引 2677。
- 数组最终顺序确定时才输出对应字符串。
- 不匹配的普通函数不会被误判为 decoder。
- 测试不能依赖固定函数名、object ID 或数组索引。

### P1：跟踪闭包 context slot 来源

`ensureDefined("name")`、`script_context[N]` 和
`context_slot(context, N, M)` 当前不能提供可靠的跨函数定义链。

需要完成：

- 建模 parent context 创建过程和嵌套函数的 context depth。
- 将已知 slot 关联到定义函数和赋值 bytecode offset。
- 在函数边界输出捕获变量。
- 对 script context 和 function context 使用统一表示，同时保留 depth 和 slot。
- 来源不唯一时输出明确的 unknown 标记。

验收条件：

- context chain 静态可知时，可以从嵌套函数读取追踪到定义位置。
- `ensureDefined` 能输出已知的来源函数和 bytecode offset。
- 测试覆盖 slot shadowing 和多层 context depth。

### P2：模拟有限的字符串数组 shuffle

只考虑有严格边界、无外部副作用的常量数组重排，不实现通用 JavaScript 执行。

需要完成：

- 只识别常量 `push`、`shift`、有限 `splice` 和整数运算组成的受限模式。
- 使用内部数据模型模拟，不能执行恢复出的 JavaScript。
- 操作不受支持或循环次数无法证明时，将数组标记为动态重排。
- 对操作数、数组长度和迭代次数设置明确上限。

验收条件：

- 小型纯旋转 fixture 可以稳定恢复。
- 不受支持的逻辑保持可见，并阻止不安全的字符串替换。

### P2：澄清 `isUndetectable`

需要从原始 bytecode instruction 开始，沿对应 V8 版本和当前 translator 路径
核对语义，再决定是否调整表达式或只补充说明。

验收条件：

- 使用聚焦 bytecode fixture 验证准确语义。
- 输出中标明来源 V8 bytecode operation。
- 现有控制流重建结果不受影响。

## 完成门槛

每项实现都必须：

- 修改行为前添加聚焦回归测试。
- 使用对应 V8 版本的真实 cache；涉及 snapshot 时使用 checksum 匹配的文件。
- 运行完整 Python 测试和相关 profile/version matrix。
- 比较修改前后的 bytecode-array 数量及 instruction metadata。
- 对不支持的 V8 布局输出明确错误，不依赖猜测的 offset、object type 或业务名称。
