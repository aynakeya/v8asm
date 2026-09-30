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
| `delete-property` | 严格/非严格删除，计算键与 Symbol、不可配置属性、原始值、null、Proxy 拒绝删除 |
| `call-order` | 方法 receiver 与参数求值顺序 |
| `property-effects` | getter 的执行次数和顺序 |
| `short-circuit` | 逻辑表达式与空值合并 |
| `optional-nullish` | 可选计算属性、getter、可选方法调用；空值跳过参数，0/false/空字符串不走 fallback |
| `default-rest-spread` | 默认值只对 undefined 生效；rest/spread、receiver、实参数量；unmapped arguments 不与形参联动 |
| `object-rest-spread` | 计算键转换、getter 次数/顺序、Symbol 保留与排除、函数命名、`__proto__` 自有属性、null prototype、null/undefined/字符串 spread |
| `literal-effects` | 对象复制和计算键的顺序、绕过原型 setter 的自有属性定义、getter/setter 名称与描述符、方法与普通函数的可构造性区别、嵌套空数组的独立身份、空/非空及嵌套对象的 null prototype |
| `expression-statements` | 未使用的对象 spread、连续表达式和算术表达式仍执行副作用，语句边界不变成连续调用 |
| `object-members` | 字符串/数字方法名、普通函数与方法的构造行为、计算键和 Symbol getter/setter、调用型键的辅助实现、重复成员与数据属性覆盖 |
| `closures`、`context-depth` | 闭包状态、同名绑定、context 层级 |
| `lexical-initialization` | 闭包、寄存器与脚本级 TDZ、重复调用的独立状态、显式 undefined、typeof 未定义全局变量与 getter 异常 |
| `try-catch`、`try-finally` | 异常与 return/throw/finally completion |

## 生成和运行

无版本后缀的 cache 使用 Node **24.7.0** / V8 **13.6.233.10-node.26**，生成参数为
`--no-lazy`。新增文件或修改源码后，应同时重新生成对应 `.jsc`：

```bash
nvm use 24.7.0
node -p 'process.versions.v8'
node --no-lazy tests/fixtures/generate_cached_data.cjs \
  tests/semantic_fixtures/<name>.js tests/semantic_fixtures/<name>.jsc
uv run python -m unittest discover -s tests -p test_semantic_equivalence.py
```

`object-rest-spread` 和 `lexical-initialization` 各有三份跨大版本 cache，均来自各自同一个 `.js` 文件：

| Node | 实际 V8 | cache 文件后缀 |
| --- | --- | --- |
| 18.20.8 | `10.2.154.26-node.39` | `-10.2.154.26.jsc` |
| 20.20.2 | `11.3.244.8-node.38` | `-11.3.244.8.jsc` |
| 22.17.0 | `12.4.254.21-node.26` | `-12.4.254.21.jsc` |

修改该源码时用表中对应 Node 重新生成三份版本缓存，不用当前 Node 冒充其他版本。
`numeric-conversion`、`delete-property`、`expression-statements` 与 `object-members`
另有 Node 18.20.8 生成的 10.2 cache，覆盖
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

## 待补范围

按实现顺序补齐行为 fixture，不一次铺满只有源码、没有正确性断言的样本：

1. class：构造器、实例/静态方法、访问器、继承与 super；随后是字段和私有成员。
2. 数组解构、嵌套/default 解构；对象复制继续覆盖 Proxy、不可枚举/继承属性及 getter 抛错。
3. 迭代器和 generator：next/return/throw、提前 break 时的 IteratorClose、yield*。
4. async/await：Promise 完成和拒绝、异常/finally 顺序；需先让观察器等待异步完成。
5. 循环内 let 捕获、多个 block/catch context、带标签的 break/continue、switch fallthrough。

`tests/decomp_rounds/cases` 已有其中一些语法样本，但编译成功或输出无未知指令不等于
语义等价。关键行为稳定后再加入对应大版本的缓存验证，不因每次小改动重建完整矩阵。
