# V8 开发环境、补丁与构建规则

本文记录原生 `v8asm` 的唯一推荐构建流程。目标是保证 V8 tag、依赖、patch、
GN 参数和生成的 startup snapshot 可以互相对应，同时复用已有编译缓存。

## 目录和环境

本机约定：

```text
项目仓库：/home/aynakeya/workspace/v8asm
官方 V8 checkout：/home/aynakeya/workspace/tmp/v8test/v8
环境入口：/home/aynakeya/workspace/tmp/v8test/start_env.md
depot_tools：由 start_env.md 设置
```

V8 checkout 必须来自 Google 推荐的 `fetch v8` 流程，而不是单独
`git clone https://chromium.googlesource.com/v8/v8.git`。`gclient` 管理的依赖和
hooks 是可构建 checkout 的一部分。

每次调用 `gclient`、`gn`、`autoninja` 或 V8 辅助工具前都先加载环境：

```bash
cd /home/aynakeya/workspace/tmp/v8test
source start_env.md
cd v8
```

## 切换版本的固定流程

切换 V8 tag 后必须同步依赖，再应用对应 patch：

```bash
git checkout <精确的-V8-tag>
gclient sync --with_branch_heads --with_tags
git apply --3way --recount \
  /home/aynakeya/workspace/v8asm/v8patch/<对应-patch>
```

禁止省略 `gclient sync`。不同 V8 大版本的 DEPS、build config、Torque 生成物和
第三方依赖都可能不同。只切 Git revision 而沿用未同步依赖，会让编译结果无法作为
版本适配证据。

同时遵守以下限制：

- 不使用 `gclient sync -D`。它可能删除仍要复用的依赖目录。
- 不手动删除 `out/`，也不为了“干净”构建清除 Ninja/GN cache。
- depot_tools 提示存在旧目录时，先保留；只有确认依赖冲突且用户同意后再清理。
- V8 checkout 在应用 patch 前必须没有 tracked diff。
- 构建并发固定为 `autoninja -j10`，不要改成自动占满全部 CPU。

## 输出目录和缓存

每个兼容形态使用独立且稳定的输出目录：

```text
out/v8asm.10.8.node.x64.release
out/v8asm.10.8.electron.x64.release
out/v8asm.13.2.152.41.electron.x64.release
out/v8asm.13.2.152.41.electron.nostaticroots.x64.release
out/v8asm.13.4.114.21.electron.staticroots.x64.release
out/v8asm.13.6.node24.x64.release
```

版本相同但 pointer compression、sandbox、static roots 或 embedder 不同，也必须
使用不同目录。不要覆盖另一个形态的 `args.gn`。

增量重建示例：

```bash
gn gen out/v8asm.13.4.114.21.electron.staticroots.x64.release \
  --args='is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_enable_sandbox=true v8_enable_static_roots=true v8_embedder_string="-electron.0"'

autoninja -j10 \
  -C out/v8asm.13.4.114.21.electron.staticroots.x64.release \
  v8asm
```

构建后不能只看当前 source branch，必须查询 binary：

```bash
out/<目录>/v8asm version
out/<目录>/v8asm build-args
```

旧 `out/` 目录中的 binary 可能来自上一次 checkout。binary 自己报告的版本和参数
才是运行时证据。

## 补丁对应关系

| Patch | 主要 tag | 关键差异 |
| --- | --- | --- |
| `v8asm-10.2.patch` | `10.2.154.4`、`10.2.154.26` | 旧 cached-data header，没有 RO checksum 字段 |
| `v8asm-10.8.patch` | `10.8.168.25` | 10.8 已有新版 `BytecodeArray::Disassemble`，不能直接套 10.2 patch |
| `v8asm-11.3.patch` | `11.3.244.8` | 旧对象 API，header 仍无 RO checksum 字段 |
| `v8asm-11.4.patch` | `11.4.183.14` | startup snapshot 版本字符串可能位于 offset 12 |
| `v8asm-11.9.patch` | `11.9.169.7` | 11.x cast、ScriptOrigin 和 TrustedObject API |
| `v8asm-12.4.patch` | `12.4.254.12`、`12.4.254.21` | Node 22 需要无 pointer-compression 变体 |
| `v8asm-12.9.patch` | `12.9.202.28` | 12.x TrustedObject sandbox guard |
| `v8asm-13.2.patch` | `13.2.152.41` | Electron static-roots 与反向探针都已定义 |
| `v8asm-13.4.patch` | `13.4.114.14`、`13.4.114.21` | Atom 路径包含受控的 external-reference 兼容逻辑 |
| `v8asm.patch` | `13.6.233.8`、`13.6.233.10` | 当前主 patch；不能代替 13.4 baseline 加载 Atom snapshot |

10.8 必须使用专用 patch。10.8 源码已经包含 10.2 patch 试图补入的 handle-based
constant-pool/handler-table 反汇编逻辑，直接执行 10.2 的 3-way apply 会在
`src/objects/code.cc` 和 `src/snapshot/code-serializer.cc` 冲突。

## 常见构建形态

Node 风格通常需要：

```text
v8_enable_pointer_compression=false
v8_enable_sandbox=false
v8_enable_static_roots=false
```

Electron 风格通常需要：

```text
v8_enable_pointer_compression=true
v8_embedder_string="-electron.0"
```

较新的 Electron snapshot 还可能要求：

```text
v8_enable_sandbox=true
v8_enable_static_roots=true
```

这些只是矩阵中已验证形态的起点，不是按产品名称推导 build flags 的通用公式。
最终必须以目标 runtime、snapshot 和实际失败位置验证。

## 二进制缓存规则

成功构建的运行文件保存在：

```text
tests/decomp_rounds/bin_cache/v8asm.<版本与形态>/
```

每个目录应包含：

```text
v8asm
snapshot_blob.bin
icudtl.dat
version.txt
build-args.txt
```

其中 `snapshot_blob.bin` 必须来自同一 V8 `out/` 目录，不能替换成 Electron、Node、
Chromium 或应用提供的 snapshot。`v8_context_snapshot.bin` 不得放进 bin cache。
外部 snapshot 只能通过 `--snapshot_blob` 或矩阵环境变量显式传入。

检查命令：

```bash
python3 tests/decomp_rounds/check_bin_cache.py
```

该脚本会检查 metadata 命令是否干净、snapshot 版本提示、可见 `out/` hash 对照，
并拒绝 bin cache 中的 `v8_context_snapshot.bin`。

## 构建矩阵

需要证明 patch 可以从源码重新应用并编译时，使用：

```bash
tests/decomp_rounds/build_v8asm_matrix.sh
```

也可以只重建指定行：

```bash
tests/decomp_rounds/build_v8asm_matrix.sh \
  10.8-electron \
  13.4-electron-staticroots
```

脚本对每一行执行：

1. checkout 精确 tag；
2. `gclient sync --with_branch_heads --with_tags`；
3. `git apply --3way --recount`；
4. 复用该行固定的 `out/`；
5. `autoninja -j10`；
6. 把成功产物同步到对应 bin cache；
7. 恢复 V8 checkout 中由 patch 产生的 tracked diff。

构建矩阵输出 `tests/decomp_rounds/build_matrix/summary.md`。旧目录里只有
`args.gn` 而没有 `v8asm`，不能算编译成功。

## 修改补丁的检查顺序

小改动先做静态检查：

```bash
python3 tests/decomp_rounds/check_patch_text.py
python3 tests/decomp_rounds/audit_patch_coverage.py
```

然后在干净的精确 tag 上做 3-way 检查：

```bash
git apply --3way --recount --check \
  /home/aynakeya/workspace/v8asm/v8patch/<对应-patch>
```

最后才执行增量构建和 runtime 验证。patch 能应用、bin cache 存在、runtime 能加载
外部 Electron cache 是三个不同等级的证据，不能互相替代。

## 容易误判的情况

- `version_hash` 相同不表示 flags、magic、RO heap 或对象布局相同。
- source checkout 在正确 tag，不表示正在运行的 `out/.../v8asm` 也是该版本。
- `version`、`build-args` 是 metadata 命令，不应通过 wrapper 自动附加外部 snapshot。
- `fixed_offset` 不是 header 小问题，应重新编译匹配 static-roots 的 binary。
- forced disasm 能退出 0，不表示输出完整；仍要检查 crash signature、对象占位符和
  decompiler 质量指标。
