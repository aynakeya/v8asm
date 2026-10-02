# 完整应用 fixture：Taskboard

这是一个可运行的内存任务管理 CLI，不是把互不相关的语法片段拼成一个文件。
核心源码在 `tests/application_fixture/taskboard.js`，376 行；命令行入口为同目录的
`taskboard.cjs`。支持新增任务、修改、完成、筛选、撤销、事务和审计事件。
所有场景使用固定输入，不访问网络、磁盘业务数据、时钟或随机数。

这组样例用于发现能力缺口，不是已经全绿的兼容性承诺。小型语义门禁仍在
`tests/semantic_fixtures/`；完整应用诊断按需运行，不加入每次修改的默认测试。

## 直接使用

在项目根目录运行，多个参数就是同一块任务板上依次执行的命令：

```bash
node tests/application_fixture/taskboard.cjs \
  'add "repair parser" --priority=3 --tags=v8,js' \
  'add "review scopes"' 'done T1' 'list --open'

# 不传参数时运行新增、更新、查询和撤销示例。
node tests/application_fixture/taskboard.cjs

# 独立运行高级场景。
node tests/application_fixture/taskboard.cjs --case async
```

任务存放在本次进程的内存中，不在两次调用间持久化。输出 JSON 同时包含业务结果、
错误结果和副作用顺序。事务失败恢复任务内容；revision 和 audit 是保留的审计历史，
不会随撤销倒退。

## 场景

| 场景 | 组合覆盖 |
| --- | --- |
| `parser` | 正则、matchAll、数组解构、rest、默认值、模板字符串、`??=`、`||=` |
| `workflow` | Map/Set/WeakMap、Symbol、闭包、getter、默认参数、对象/数组 spread、字符串 switch、回调、可选调用、撤销 |
| `transactions` | 嵌套闭包、监听器注销、try/catch/finally、catch 解构、异常回滚和副作用次序 |
| `selection` | 标签循环、跨层 break/continue、嵌套解构、每轮 let 捕获 |
| `plugins` | Proxy/Reflect、自有属性描述符、不可枚举属性、对象 rest、Symbol 键、ToPrimitive、可选链、逻辑赋值 |
| `iterators` | 自定义 iterator、next/return、continue/break/throw、IteratorClose 和 finally |
| `classes` | 构造器、静态方法、getter/setter、解构参数、方法 receiver 和严格模式异常 |
| `advanced_classes` | extends/super、私有字段、私有品牌检查、实例/静态字段、static block、计算方法名、箭头函数捕获 this |
| `generators` | yield/yield*、next(value)、return、throw、catch/finally、提前关闭 |
| `async` | await、并发 Promise 完成/拒绝、allSettled、async generator、for-await-of 提前关闭 |
| `codec` | BigInt、数值分隔符、TypedArray/DataView、tagged template、数组空洞、负零、NaN、Infinity |

暂不覆盖 ES module 链接、dynamic import、eval/with、真实 I/O 和浏览器 DOM。
这些需要不同的宿主契约，不用当前 vm.Script 样例冒充覆盖。

## 完整诊断

```bash
uv run python tests/run_application_fixture.py
```

默认使用 PATH 中的 Node，以 `--no-lazy` 编译源码为 cache，然后通过 Python
disassembler/decompiler 恢复，再分别执行源码和恢复结果。可用 `--node` 选择实际
编译和执行的 runtime，`--snapshot-blob` 指定匹配 snapshot，`--out` 指定产物目录。
不下载 runtime，不构建 V8，不使用旧 v8asm 的文本输出作为正确性标准。

默认产物在已忽略的 `tests/decomp_rounds/out/taskboard/`：

- `taskboard.jsc`：本次 runtime 真正生成的 cache；
- `taskboard.disasm.json`：完整对象图、bytecode 和 profile/snapshot 元数据；
- `taskboard.decompiled.js`：完整反编译结果，包含辅助 runtime；
- `<场景>.isolated.js`：从同一对象图恢复出的完整相关函数树及入口；
- `report.json`：实际 Node/Electron/V8 版本、源码/cache SHA-256、编译参数、
  snapshot 路径和解析元数据、WARNING、语法检查、逐场景结果与第一个差异路径。

完整文件存在语法错误时，所有完整应用场景都会失败。为继续定位其他问题，诊断器
另外从 bytecode 元数据恢复指定子系统的函数树，包括其全部嵌套函数；不改写恢复
结果、不删除未实现指令。子系统只排除不相关的顶层函数，不能证明整个文件可执行。
`summary.passed` 与 `summary.isolated_passed` 分开统计，后者绝不能抵消前者的失败。

退出码只有在全部完整场景等价、没有 WARNING 和管线错误时才为 0。源码本身抛错、
双方都抛相同错误、Promise 不完成、进程超时，都不会记为通过。

观察器在 vm 的 microtask 队列排空后读取结果；标记 BigInt、undefined、负零和
非有限数值，避免普通 JSON 丢失这些差异。数组空洞由场景显式检查索引是否存在。
vm 执行限时 2 秒，Python 子进程限时 8 秒，串行运行。
该 vm 只用于自写 fixture 和恢复代码的验证，不是运行不可信应用的安全沙箱。

## 匹配 Electron 的实测

2026-10-02 使用本地已有的官方 Electron **35.7.5**，实际 V8 为
**13.4.114.21-electron.0**。同一个 executable 编译 cache、执行原源码和恢复代码：

```bash
ELECTRON_DIR=/home/aynakeya/workspace/tmp/v8test/electron-cache/v35.7.5-linux-x64
ELECTRON_RUN_AS_NODE=1 uv run python tests/run_application_fixture.py \
  --node "$ELECTRON_DIR/electron" \
  --snapshot-blob "$ELECTRON_DIR/v8_context_snapshot.bin" \
  --out tests/decomp_rounds/out/taskboard-electron-35-numeric-literals
```

这份 cache 的 read-only checksum 为 `0x4e6b3214`，与 `v8_context_snapshot.bin`
匹配。该 release 的 `snapshot_blob.bin` 为 `0xa151feb8`，实际尝试会被拒绝；
不能只看文件名或相同版本号就认为可以互换。

共解析出 **65 个 BytecodeArray**。原始源码的 11 个场景均成功，完整恢复文件仍被
派生类中的非法 `this = ...` 阻断，完整应用为 **0/11**；隔离子系统为 **7/11**：

| 结果 | 场景 | 当前证据 |
| --- | --- | --- |
| 行为一致 | parser、workflow、transactions、selection、plugins、iterators、classes | 结果、异常处理结果和记录到结果中的副作用顺序一致；任务数组物化和回滚已恢复 |
| 语法错误 | advanced_classes | `this = r6` 等非法赋值；派生构造、super、字段初始化仍未恢复 |
| 运行错误 | generators | `CreateJSGeneratorObject` 未定义，yield 状态机尚未恢复 |
| 运行错误 | async | `AsyncFunctionEnter` 未定义，await/resume 尚未恢复 |
| 运行错误 | codec | 数值/稀疏数组已恢复；`GetTemplateObject` 仍有 WARNING，读取模板的 `raw[0]` 失败，BigInt 常量也尚未解码 |

Node **24.7.0 / 13.6.233.10-node.26** 的无 snapshot 对照也已运行。该输入中的
`.push`、`.toLowerCase` 等来自 RO heap，缺少对应 snapshot 时保留占位符，不能把
这些错误全部归咎于 decompiler。Electron 的匹配 snapshot 对照就是为了排除这类干扰。

## 本轮已修复

从完整应用提取独立可复现问题，修复后固定到小型语义测试：

1. `catch ({ code, message })` 的内部 `.catch` 被当作变量名打印。现在使用合法的
   scope 派生名称，不直接透传内部名称；覆盖 V8 10.2、11.3、12.4、13.6。
2. `let next = 0; return { next() { return ++next; } }` 的方法临时变量与捕获变量
   重名。现在分配临时方法名时避开已知 lexical 名称，保留真实方法 `.name`；
   覆盖 V8 10.2、13.6。
3. 字符串 switch 的后续 case 错误进入 default。未能结构化的剩余跳转现在回到
   显式 CFG dispatch，不把它当作可忽略注释。真实 cache 覆盖 case、default、
   fallthrough 和输入类型，另有 Constant 分支的执行测试。
4. `ToNumber`、`Negate` 和 `CreateArrayFromIterable` 直接恢复原生一元运算和数组
   spread；覆盖 Symbol/BigInt、负零、转换顺序、稀疏数组物化、iterator getter 和异常。
   四个 V8 大版本的真实 cache 均通过；原来失败的 workflow 和 transactions 现在一致。
5. 修复两处后处理误删：`...ACCU` 未被识别为读取，以及短路分支之外仍使用的比较结果。
   另修复 Node 20.20.2 root 回移引起的 `next`/`resolve` 错位，使用官方源码生成的
   精确版本布局。生成入口、版本与产物记录见[生成资产](generated-assets.md)。
6. 补齐 HeapNumber/FixedDoubleArray 与重复 serializer 引用，区分空洞、undefined、
   负零和非有限数。独立的 `numeric-literals` fixture 在 V8 10.2/11.3/12.4/13.6
   的 Node cache 上行为一致；另由此 Electron 编译、加载匹配 context snapshot、
   执行源码和恢复代码，4 字节 tagged 布局也通过。诊断产物在
   `tests/decomp_rounds/out/numeric-literals-electron-35/`。这个独立成功不代表 codec
   的模板和 BigInt 已经支持。

对应测试入口：

```bash
uv run python -m unittest discover -s tests -p test_semantic_equivalence.py
uv run python -m unittest discover -s tests -p test_application_fixture.py
```

第二条测试验证原始应用与观察器契约，不表示反编译后的完整应用已经通过。

## 接下来的优先级

1. **P1：派生类与 lexical this。** 首先不能输出非法赋值，再根据对象图和实际
   bytecode 恢复 super/初始化语义，不能把 `this = ...` 直接删掉。
2. **P1：generator 与 async。** 分别恢复 suspension/resume/completion，保留
   return/throw/finally 次序；不能添加返回 undefined 的假 helper 来绕过错误。
3. **P1：模板对象与 BigInt 常量。** 恢复 raw/cooked 数组、冻结状态、同一调用点的
   身份及不同调用点的区别。BigInt 必须从源码布局恢复，不经 Number 中转；
   不根据某一版本中的偏移或对象编号跨版本猜测。
4. **P2：可读性。** 正确性稳定后，把显式 dispatch 恢复成原生 switch/for-of/try，
   最后考虑变量命名；业务用途猜测和混淆字符串解码仍不属于 fidelity decompiler。

这组样例是后续改进的输入，不要求一次铺满全部版本矩阵。先修明确根因、通过对应
小型行为测试，再选择旧/新大版本缓存；涉及 Electron RO 对象时保留匹配 snapshot 对照。
