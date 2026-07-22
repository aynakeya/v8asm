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

对 parser、结构化 schema 和 decompiler 的默认门禁：

```bash
python3 -m unittest discover -s tests -v
```

关键测试范围包括：

- 24/28 字节字段布局和动态 header padding；
- raw payload 的显式 offset 与错误输入拒绝；
- serializer 对象、FixedArray 和 literal boilerplate；
- snapshot page、static roots、relocation 和字符串边界；
- 结构化 JSON schema、对象引用和 deterministic order；
- SFI、ScopeInfo、闭包树和 context slot；
- opcode translation、控制流恢复和文件级后处理；
- 方法调用折叠的正向与反向语义测试。

2026-07-22 最近一次完整运行结果为 189 个测试通过。这个数字只用于定位基线；新增测试
后应更新日期和结果，不把测试数量作为功能本身。

## 补丁与二进制缓存检查

不切换 V8 branch 的轻量检查：

```bash
python3 tests/decomp_rounds/check_patch_text.py
python3 tests/decomp_rounds/audit_patch_coverage.py
python3 tests/decomp_rounds/check_bin_cache.py
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
python3 tests/decomp_rounds/check_electron_snapshot_round.py
python3 tests/decomp_rounds/check_electron_version_matrix.py
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
python3 tests/decomp_rounds/fetch_electron_releases.py 34.3.0
python3 tests/decomp_rounds/check_electron_version_matrix.py
```

不要删除已有 zip 或解压目录。官方 stable 覆盖审计使用：

```bash
python3 tests/decomp_rounds/audit_electron_release_coverage.py
```

## 当前官方 Electron 样本覆盖

以下行有 exact Linux x64 Electron release 作为外部样本：

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
