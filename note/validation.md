# 验证方法与版本覆盖

V8 兼容性不能用“patch 文件存在”或“命令退出 0”证明。本文定义从静态检查到真实
Electron 样本的证据等级，以及修改后应运行的验证入口。

## 证据等级

从弱到强依次为：

1. **静态 patch 检查**：关键 hook 存在，没有明显漏同步。
2. **3-way apply**：patch 能在精确 tag 的干净 checkout 上应用。
3. **源码构建**：同步依赖后，以记录的 GN 参数用 `autoninja -j10` 编译成功。
4. **self-cache**：该 binary 自己生成的 cache 可以 strict disasm 和 decompile。
5. **匹配 Node/bytenode**：numeric V8 和 pointer layout 对应的 Node cache 可以加载。
6. **官方 Electron release**：由 exact Electron runtime 生成 cache，并显式测试 release
   中两个 snapshot。
7. **目标应用样本**：目标应用真实接受的 cache、snapshot 和构建形态完整通过。

高等级证据可以回答更具体的问题，但不能反向证明所有低版本或其他 embedder。某个
Electron release 通过，不表示同 numeric V8 的所有应用 snapshot 都兼容。

## Python 单元测试

先在根目录运行 `uv sync --locked`。日常修改只运行对应模块的测试，例如：

```bash
uv run python -m unittest discover -s tests -p test_disassembler.py
uv run python -m unittest discover -s tests -p test_semantic_equivalence.py
```

跨模块的大型修改或准备提交时，可运行完整 Python 测试：

```bash
uv run python -m unittest discover -s tests -v
```

关键测试范围包括：

- 24/28 字节字段布局和动态 header padding；
- raw payload 的显式 offset 与错误输入拒绝；
- serializer 对象、FixedArray 和 literal boilerplate；
- snapshot page、static roots、relocation 和字符串边界；
- 结构化 JSON schema、对象引用和 deterministic order；
- SFI、ScopeInfo、闭包树和 context slot；
- opcode translation、控制流恢复和文件级后处理；
- 方法调用折叠的正向与反向语义测试；
- 原始 JavaScript 与恢复结果的可执行语义等价测试，包括 getter 副作用、
  closure/context shadowing、TDZ、typeof、数值转换、delete、短路和 `try/catch/finally` completion；
- root、read-only、object cache 和 attached reference 的来源与类型证据。

语义 fixture 使用指定的 Node/V8 版本生成 cache：

```bash
uv run python tests/generate_semantic_fixtures.py <name>
```

测试分别在隔离的 Node `vm` 中执行源码和带轻量 runtime 的恢复结果，比较返回值或异常。
文本更短、寄存器更少或测试不抛异常都不能替代这个比较。

fixture 的特性范围、生成版本和待补缺口见
[语义 fixture 说明](semantic-fixtures.md)。普通源码 fixture 不依赖
被忽略的本地 `bin_cache`；必须使用外部 snapshot 的测试应明确记录获取方式和版本。

### 2026-10-01 小版本候选复检

范围包括转换与 iterable 指令、逐指令作用域、同步异常控制流、基础 class 恢复，
以及完整 Taskboard 样例发现的 catch、命名、switch 和临时值误删问题：

- 完整 Python 测试：**235 项通过，无跳过**；
- `conversion-boundaries`、`iterable-spread`、`context-lifetimes`、
  `exception-completions`、`class-members` 的 V8 10.2、11.3、12.4、13.6 真实 cache
  均通过源码与恢复结果的执行对照；
- Node 20.20.2 的 root 回移由官方源码生成独立布局；完整版本选型已通过实际 cache
  验证，不能改用数字版本 profile 来冒充兼容；
- 本轮转换/iterable cache 使用固定生成器重新生成，记录实际 runtime 和 SHA-256，
  执行测试同时检查源码/cache 是否过期；
- 14 个 profile 的 handler/class 布局从各自精确 tag 生成，并检查新旧代表版本
  的完整生成器输出与工作区 JSON 一致；
- 前一轮 Atom 使用 `example2/atom.compiled.dist.jsc`、V8 `13.4.114.21` 和
  `example2/v8_context_snapshot.bin` 重新解析，恢复代码通过 `node --check`；
  WARNING 和 raw goto 为零，仍保留 8 处 goto 注释。

Atom 只检查对象解析、生成诊断和 JavaScript 语法，没有执行目标应用。
复杂异常或迭代器结构可能保留显式 dispatch；基础 class 测试不覆盖继承、私有字段
等尚未支持的结构。本轮没有修改原生 patch，也没有重新构建或验证 Electron 二进制矩阵。

### 完整应用样例

应用诊断另用官方 Electron 35.7.5 / V8 13.4.114.21-electron.0 编译真实 cache，
加载 checksum 匹配的 `v8_context_snapshot.bin`：11 个原源码场景成功，完整恢复文件
仍有派生类语法错误；**7 个隔离子系统行为一致**，比修复 iterable 前增加任务流程和事务
两个场景。完整应用仍为 **0/11**，诊断命令退出 1，不能记作整体验证通过。
Node 24.7.0 无 snapshot 的结果与错误 snapshot 的拒绝结果另存为对照。

本轮可作为已覆盖语言子集的增量版本候选，不是任意 JS 的完整可执行还原承诺。
派生类/私有字段、generator/async 和稀疏 double array/tagged template 仍是明确缺口，
详见 [Taskboard 报告](application-fixture.md)。没有创建 tag、修改版本号或发布产物。
生成配方与可重复使用的入口统一记录在[生成资产](generated-assets.md)。

### 2026-10-02 数值与稀疏数组

上一轮基线已提交为 `c18ee0a`。本轮继续修复数值对象、serializer 重复引用和
分支 ACCU 语义，不构建 V8、不更改其源码或编译缓存：

- 全量运行 238 项，236 项在沙箱内通过；两项 checkversion 多进程测试因本地 socket
  限制中断，随后仅对这两项在沙箱外重跑，均通过。无跳过；
- `numeric-literals` 在 Node 18.20.8、20.20.2、22.17.0、24.7.0 的真实 cache 上
  均与源码行为一致；生成信息、源码/cache 校验值已记录到 manifest；
- 官方 Electron 35.7.5 / V8 13.4.114.21-electron.0 同样编译并执行该样例，加载
  checksum 匹配的 context snapshot，4 字节 tagged 形态行为一致，WARNING 为零；
- 数值布局从 14 个精确 V8 tag 重新生成；测试拒绝越界/缺失数值数据、重复引用越界、
  缺少数值字段的旧 JSON 和无法确认构建开关的 undefined-NaN 编码；
- Taskboard 重新运行仍为完整 0/11、隔离 7/11。codec 的数组错误已消失，但模板与
  BigInt 未实现，不把错误位置后移记成场景通过。

本机原 `.venv` 指向已不存在的 `/usr/bin/python3.12`。本轮采用临时 uv 环境和系统
Python 3.14.4，保留 `.python-version` 与原 `.venv`，没有悄悄修改项目 Python 约定。
复现临时验证环境可给 uv 命令加以下前缀：

```bash
UV_PROJECT_ENVIRONMENT=/tmp/v8asm-venv-314 \
  uv --cache-dir /tmp/v8asm-uv-cache run --python /usr/bin/python3 --locked --offline \
  python -m unittest discover -s tests -p test_semantic_equivalence.py -k numeric_literals
```

损失精度的文本 printer 不作为新数值功能的输入依据；需要重新生成 `--format json`。
JavaScript 运行时对 NaN 的表示允许规范化，不宣称任意 NaN payload 经执行仍逐位相同。

### 何时运行矩阵

- 普通表达式和 opcode 修复：相关单元测试与语义 fixture。
- 共享后处理、闭包或 CFG 改动：再跑 `test_decompiler_file.py`，其中已有 V8
  10.2、11.3、12.4、13.6 的缓存回归，不需要重编 V8。
- profile、serializer、snapshot 或 patch 改动：按影响范围选择 Node/Electron
  版本矩阵；发布或声明完整兼容时才扩展为完整矩阵。

缓存能够解析、输出结构断言通过、执行语义等价是不同证据。多版本结构测试不能冒充
所有 JS 特性在这些版本上都执行等价；新增关键特性稳定后再补对应版本的语义样本。

## 补丁与二进制缓存检查

不切换 V8 branch 的轻量检查：

```bash
uv run python tests/decomp_rounds/check_patch_text.py
uv run python tests/decomp_rounds/audit_patch_coverage.py
uv run python tests/decomp_rounds/check_bin_cache.py
```

职责分别是：

- `check_patch_text.py`：确认各 patch 的关键保护和参数路径没有遗漏；
- `audit_patch_coverage.py`：报告 patch family 的 Node/Electron bin cache 覆盖；
- `check_bin_cache.py`：检查 binary metadata、构建参数和 sibling snapshot 来源。

`audit_patch_coverage.py` 默认是报告工具。只有要声明全部预期行都具备缓存 binary 时才用
`--strict`。

## 源码重建门禁

证明 patch 仍可应用和编译时运行：

```bash
tests/decomp_rounds/build_v8asm_matrix.sh
```

聚焦指定版本：

```bash
tests/decomp_rounds/build_v8asm_matrix.sh \
  10.8-electron \
  13.2-electron \
  13.4-electron-staticroots
```

脚本必须执行精确 tag checkout、`gclient sync --with_branch_heads --with_tags`、
`git apply --3way --recount` 和 `autoninja -j10`，并复用每行原有 `out/`。完整构建规则
见 [environment-and-build.md](environment-and-build.md)。

仅执行 `git apply --check` 不能证明编译；仅发现旧 `out/.../v8asm` 也不能证明它来自
当前 source。每个产物都要记录 `v8asm version` 和 `v8asm build-args`。

## 轻量 Node 与自生成缓存矩阵

```bash
tests/decomp_rounds/run_version_matrix.sh
```

默认流程：

- 枚举 `tests/decomp_rounds/bin_cache/*/v8asm`；
- 对每个 binary 生成 self-cache，并要求 strict disasm 和源码恢复成功；
- 使用本地 nvm 中的 Node 18、20、22、24 生成 bytenode cache；
- 只有 numeric V8 和 pointer-compression 形态匹配时才要求 forced load；
- 检查 crash signature、raw goto、未知 opcode 和对象失败占位符。

当前 Node 对照关系：

| Node | `process.versions.v8` | 主要构建形态 |
| --- | --- | --- |
| 18.20.8 | `10.2.154.26-node.39` | pointer compression 关闭 |
| 20.20.2 | `11.3.244.8-node.38` | pointer compression 关闭 |
| 22.17.0 | `12.4.254.21-node.26` | pointer compression 关闭 |
| 24.7.0 | `13.6.233.10-node.26` | pointer compression 关闭 |

bytenode 必须在表中对应 Node 下实际生成，不能拿一个 Node 版本的 `.jsc` 证明另一个 V8
版本。numeric 版本或 pointer layout 不匹配的 forced probe 只能作为研究信号。

## Electron 发行版矩阵

真实 Electron 门禁：

```bash
uv run python tests/decomp_rounds/check_electron_snapshot_round.py
uv run python tests/decomp_rounds/check_electron_version_matrix.py
```

版本矩阵会从每个 Electron binary 读取 `process.versions.v8`，只选择 exact numeric V8
的 Electron-flavored `v8asm`，由该 Electron 运行时生成 bytenode cache，再分别测试：

```text
snapshot_blob.bin
v8_context_snapshot.bin
```

不能根据文件名预先认定哪一个匹配。strict/forced 结果、RO checksum、static-roots 和
decompiler 质量必须一起记录。

缺少 release 时复用本地下载缓存：

```bash
uv run python tests/decomp_rounds/fetch_electron_releases.py 34.3.0
uv run python tests/decomp_rounds/check_electron_version_matrix.py
```

不要删除已有 zip 或解压目录。官方 stable 覆盖审计使用：

```bash
uv run python tests/decomp_rounds/audit_electron_release_coverage.py
```

## 已定义的 Electron 验证行

以下配置使用 exact Linux x64 Electron release 作为外部样本。是否通过以当前代码的
运行结果为准，不把版本表当作持续有效的测试报告：

| Electron | V8 | 对应 patch |
| --- | --- | --- |
| 19.0.4 | `10.2.154.4-electron.0` | `v8asm-10.2.patch` |
| 22.3.27 | `10.8.168.25-electron.0` | `v8asm-10.8.patch` |
| 25.0.1 | `11.4.183.14-electron.0` | `v8asm-11.4.patch` |
| 30.0.1 | `12.4.254.12-electron.0` | `v8asm-12.4.patch` |
| 34.3.0 | `13.2.152.41-electron.0` | `v8asm-13.2.patch` |
| 35.7.5 | `13.4.114.21-electron.0` | `v8asm-13.4.patch` |
| 36.2.1 | `13.6.233.8-electron.0` | `v8asm.patch` |

`11.3.244.8`、`11.9.169.7` 和 `12.9.202.28` 当前没有稳定 Linux x64 Electron
release 的 exact 外部样本证据。它们可以有源码构建和 self-cache 覆盖，但在找到匹配
Electron 包或目标应用 snapshot 前，不应写成“Electron 已验证”。

## 版本配置与补丁覆盖不是同一个集合

Python profile 描述源码 tag 的静态格式；原生 patch 描述该 tag 上的 v8asm 改动；bin
cache 表示某组 GN 参数曾成功构建；Electron release 测试则证明某个真实 embedder
样本。四者应分别审计。

例如：

- profile 解析成功，不证明原生 startup snapshot 能加载；
- patch 能 3-way apply，不证明 Electron external-reference 表兼容；
- self-cache 通过，不证明外部 `.jsc` 的 RO checksum 匹配；
- forced disasm 退出 0，不证明所有字符串和对象都已还原。

## 输出质量门禁

矩阵不能只看进程退出码。至少检查：

```text
SIGSEGV、SIGABRT、CHECK/DCHECK、FATAL、sanitizer 报错
raw_goto
unknown_comments
undefined_fallbacks
BytecodeArray 数量异常下降
输出为空或只含 header
```

默认 `raw_goto` 和 `unknown_comments` 上限为零。需要临时提高阈值时，必须在验证记录中
写明具体样本和原因，不能把宽松阈值提交成新的默认标准。
`unknown_comments` 同时识别旧版原始指令注释和当前 `WARNING`，包括带 offset 的 linear
输出及整函数恢复失败；不能因诊断格式变化而漏报。

对于目标应用，最终门禁应使用应用实际接受的 cache。磁盘 `.jsc` 无法解析但应用能加载
时，先按 [python-disassembler.md](python-disassembler.md) 捕获 `vm.Script` 输入和
normalized cache，再判断是私有 wrapper 还是 V8 对象布局差异。

## 失败定位顺序

1. 先确认正在运行的 binary 版本和 build args。
2. 再确认 cache 的 numeric V8、magic、flags hash、RO checksum 和动态 header。
3. 检查使用的 snapshot 是否来自目标 runtime，且是否匹配 static-roots。
4. `fixed_offset` 通过重编匹配形态处理，不 patch 掉检查。
5. startup external-reference 错误只在已证明表差异后做窄兼容。
6. cache deserialize 成功后，再检查 BytecodeArray、对象图和字符串完整性。
7. 最后运行 decompiler 质量扫描，避免“能打印”被误认为“语义已恢复”。
