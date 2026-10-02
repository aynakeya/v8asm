# JavaScript 语义 fixture

文件位于 `tests/semantic_fixtures/`，测试入口为 `tests/test_semantic_equivalence.py`。

每组 `.js` 与 `.jsc` 保护一个可观察的语言行为。测试会将 `.jsc` 经 Python
disassembler 和 decompiler 恢复，再分别在隔离的 Node `vm` 中执行源码与恢复代码，
比较 `globalThis.__semantic_result` 或异常结果。副作用应写入结果中的事件列表，
不能只检查最终数值、输出行数或某个关键字。

当前观察结果经 JSON 序列化，因此会丢失 undefined 属性、负零和非有限数值等区别。
相应 fixture 必须主动记录属性是否存在、类型、数值文本或其他可观察标志，不能依赖
JSON 自动保留这些信息。未知 opcode 的 WARNING 会直接使语义测试失败。

## 已覆盖

| fixture | 主要行为 |
| --- | --- |
| `arithmetic` | 算术表达式 |
| `numeric-conversion` | Number/BigInt 前后置更新、转换 hint 与顺序、负零、非法 primitive、复合赋值的结果值 |
| `numeric-literals` | HeapNumber、稠密/稀疏 double array、极小/极大有限数、正负 Infinity、负零、显式 undefined 与空洞、末尾/连续空洞、重复引用、多次创建的独立性 |
| `conversion-boundaries` | 字符串转换、一元加/取负的 Number/BigInt/Symbol 边界、负零、转换 hint 与副作用顺序、零参数构造调用 |
| `iterable-spread` | 独立数组复制、稀疏数组物化、Set、Unicode 迭代、iterator/next/done/value getter 顺序与异常、无额外 IteratorClose |
| `delete-property` | 严格/非严格删除，计算键与 Symbol、不可配置属性、原始值、null、Proxy 拒绝删除 |
| `call-order` | 方法 receiver 与参数求值顺序 |
| `property-effects` | getter 的执行次数和顺序 |
| `short-circuit` | 逻辑表达式与空值合并 |
| `control-flow` | 混合 &&/|| 的全部 16 组真值路径、嵌套条件表达式、外层 else 归属、分支合流、赋值表达式与逻辑赋值的结果值、提前返回、for/while/do-while 的 continue/break 与嵌套循环、条件及更新段副作用次数 |
| `optional-nullish` | 可选计算属性、getter、可选方法调用；空值跳过参数，0/false/空字符串不走 fallback |
| `default-rest-spread` | 默认值只对 undefined 生效；rest/spread、receiver、实参数量；unmapped arguments 不与形参联动 |
| `object-rest-spread` | 计算键转换、getter 次数/顺序、Symbol 保留与排除、函数命名、`__proto__` 自有属性、null prototype、null/undefined/字符串 spread |
| `literal-effects` | 对象复制和计算键的顺序、绕过原型 setter 的自有属性定义、getter/setter 名称与描述符、方法与普通函数的可构造性区别、嵌套空数组的独立身份、空/非空及嵌套对象的 null prototype |
| `expression-statements` | 未使用的对象 spread、连续表达式和算术表达式仍执行副作用，语句边界不变成连续调用 |
| `object-members` | 字符串/数字方法名、普通函数与方法的构造行为、计算键和 Symbol getter/setter、调用型键的辅助实现、重复成员与数据属性覆盖、方法与捕获变量同名 |
| `closures`、`context-depth` | 闭包状态、同名绑定、context 层级 |
| `context-lifetimes` | 独立 block/catch 环境、分支合流、循环 let 捕获及 break/continue、默认参数 body context、重复调用的独立状态 |
| `lexical-initialization` | 闭包、寄存器与脚本级 TDZ、重复调用的独立状态、显式 undefined、typeof 未定义全局变量与 getter 异常 |
| `try-catch`、`try-finally` | 异常与 return/throw/finally completion |
| `exception-completions` | 纯 try/finally、返回与异常覆盖、循环跳转、嵌套及相邻 handler、IteratorClose 的 break/throw 路径、catch 解构 |
| `class-members` | 基类构造器、实例/静态方法、getter/setter、类自身引用、严格模式 this、方法不可构造性、名称和属性描述符 |
| `switch-routing` | 字符串 case、default、fallthrough、非字符串输入和分支返回值 |

## 生成和运行

无版本后缀的 cache 使用 Node **24.7.0** / V8 **13.6.233.10-node.26**，生成参数为
`--no-lazy`。版本与生成配方固定在同目录的 `manifest.json`；新增文件或修改源码后，
通过受版本检查的入口重新生成对应 `.jsc`：

```bash
nvm use 24.7.0
uv run python tests/generate_semantic_fixtures.py conversion-boundaries iterable-spread
uv run python -m unittest discover -s tests -p test_semantic_equivalence.py
```

`object-rest-spread`、`lexical-initialization` 以及上述新增的
`conversion-boundaries`、`numeric-literals`、`iterable-spread`、`context-lifetimes`、`control-flow`、`exception-completions`、`class-members`
各有三份跨大版本 cache，均来自各自同一个 `.js` 文件：

| Node | 实际 V8 | cache 文件后缀 |
| --- | --- | --- |
| 18.20.8 | `10.2.154.26-node.39` | `-10.2.154.26.jsc` |
| 20.20.2 | `11.3.244.8-node.38` | `-11.3.244.8.jsc` |
| 22.17.0 | `12.4.254.21-node.26` | `-12.4.254.21.jsc` |

修改该源码时用表中对应 Node 重新生成三份版本缓存，不用当前 Node 冒充其他版本。
生成器根据实际 runtime 自动选择文件后缀，默认只更新指定样例；`--all` 才更新该
runtime 配置的所有样例。记录源码/cache SHA-256、实际版本、平台和编译参数。
测试会核对已有生成记录，拒绝源码与 cache 不同步，并使用记录的完整 V8 版本选 profile。
旧 cache 尚未迁移生成记录时仍运行原有行为比较，不将清单中的配方冒充历史生成证据。
跨版本执行命令、profile 生成和复现约定统一见[生成资产](generated-assets.md)。

Node 20.20.2 的 `11.3.244.8-node.38` 包含上游数字版本之外的 root 回移；使用标准
`11.3.244.8` 布局会将 iterator 的 `next` 错解为 `resolve`。本组新增 cache 的完整版本
会选择从该 Node 官方源码生成的 root 布局，而不是硬编码 root 索引偏移。
`numeric-conversion`、`delete-property`、`expression-statements` 与 `object-members`
以及 `switch-routing` 另有 Node 18.20.8 生成的 10.2 cache，覆盖
新旧 opcode 形态，不需要为这类修改重新构建原生 V8。
测试在当前 Node 的隔离 `vm` 中对比各版本 cache 的恢复结果与同一源码；这是离线
decompiler 的跨版本语义回归，不是 Electron snapshot 兼容性证明。

新增 fixture 需在 `tests/test_semantic_equivalence.py` 中加入行为测试。执行现有测试
不需要重新生成 cache，也不需要原生 `v8asm` 或本地 `bin_cache`。缺少 Node 时会跳过
语义测试，不能把这种结果记为已验证。

`object-rest-spread` 另有不加载辅助 runtime 的执行断言，保证完整匹配时确实恢复为
原生对象语法。`tests/test_source_recovery.py` 对不能合并的边界做执行对照：对象逃逸、
仍被使用的属性键、普通函数身份、null 检查先于键转换、分支中仍需保留的 ACCU 值。

本组主要覆盖无需外部 snapshot 的缓存。Node 的某些内置字符串位于 read-only heap，
离线输入没有对应 snapshot 时仍可能显示占位符；不能为使测试通过而猜测这些字符串。
涉及 snapshot 的用例应放在明确提供匹配 snapshot 的测试中。
本组中少量内置属性名通过字符串拼接构造，使 fixture 本身不依赖外部 RO 字符串；
解析器没有为这些测试添加字符串猜测或地址特判。
数值转换 fixture 使用非内置数字字符串，避免把无法读取 RO 常量与转换指令语义混为一谈。
`numeric-literals` 的空洞观察标记使用非内置字符串；判断依据是索引是否存在，
不是标记文本。JSON 观察前先记录类型、数值字符串和负零标志，避免 JSON 把这些差异吞掉。
`control-flow` 用数组索引写入事件，不依赖 snapshot 中的内置方法名；比较短路调用的
顺序、分支赋值、迭代次数和提前退出结果，不要求输出恢复成与源码相同的循环语法。
同时观察 `?:`、`&&`、`||`、`??` 内赋值的表达式结果与赋值目标，覆盖局部变量的
`??=`、`||=`、`&&=`，区分 0、false、null、undefined 和真值路径。调用事件另行
比较，不能仅凭赋值目标正确就认为表达式结果和副作用也正确。

`test_disassembler.py` 另验证 IEEE-754 位模式的无损 JSON 表示、截断数值数据与长度越界
拒绝，以及新旧 serializer 的固定/变长重复引用。构建开关未确认的实验性
undefined-NaN 编码明确报错，不将其猜成 undefined 或普通 NaN。

`tests/test_translator.py` 另外执行验证 `ToObject` 的目标寄存器、ACCU 保持不变及
null/undefined 异常；还覆盖普通、Wide、ExtraWide switch 表中的空槽与默认分支。

## 待补范围

按实现顺序补齐行为 fixture，不一次铺满只有源码、没有正确性断言的样本：

1. 随常用控制流规则改进，扩展分支合流、循环条件/更新段、提前返回及常见异常路径。
2. 数组解构、嵌套/default 解构；对象复制继续覆盖 Proxy、不可枚举/继承属性及 getter 抛错。
3. class：继承与 super、计算键、字段、私有成员及大型 dictionary template。
4. 迭代器和 generator：next/return/throw、提前 break 时的 IteratorClose、yield*。
5. async/await：Promise 完成和拒绝、异常/finally 顺序；需先让观察器等待异步完成。
6. 带标签的多层 break/continue、动态及外部作用域。

`tests/decomp_rounds/cases` 已有其中一些语法样本，但编译成功或输出无未知指令不等于
语义等价。关键行为稳定后再加入对应大版本的缓存验证，不因每次小改动重建完整矩阵。

完整应用组合另见 [Taskboard fixture](application-fixture.md)。它保留尚未支持的
高级特性，按需输出失败报告；不把局部通过或预期失败当作完整应用等价。
