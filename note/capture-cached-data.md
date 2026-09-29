# 捕获应用实际接受的缓存

应用可能在读取 `.jsc` 后解密、解压或重写 header。此时应在应用完成变换、交给
`vm.Script` 的边界捕获 `cachedData`，而不是猜磁盘文件的 payload 偏移。
捕获脚本位于 `disassembler/capture_cached_data.cjs`，必须先于 loader 加载。

## 预加载

Linux/macOS：

```bash
V8_CACHE_DUMP_DIR=/tmp/v8-cache-dump \
NODE_OPTIONS="--require=/absolute/path/to/v8asm/disassembler/capture_cached_data.cjs" \
/path/to/electron-app
```

Windows PowerShell（示例使用无空格路径）：

```powershell
$env:V8_CACHE_DUMP_DIR = "C:\tmp\v8-cache-dump"
$env:NODE_OPTIONS = "--require=C:\src\v8asm\disassembler\capture_cached_data.cjs"
& "C:\path\to\application.exe"
```

每个进程在输出目录下建立自己的 PID 子目录：

| 文件 | 含义 |
| --- | --- |
| `0000.input.jsc` | 应用实际传入 `vm.Script` 的 buffer |
| `0000.normalized.jsc` | V8 接受后用同一 runtime 的 `createCachedData()` 重新生成的 cache |
| `0000.payload.bin` | 从 normalized cache 精确提取的无 header serializer 数据 |
| `0000.json` | PID、V8 版本、原文件名、大小、拒绝状态和 payload 边界 |

JSON 字段使用 `under_score`，`v8_version` 来自 `process.versions.v8`。
`cached_data_rejected: false` 才表示捕获输入被 V8 接受。payload 长度必须精确等于
header 后剩余字节数；布局不唯一时不输出 payload，偏移/长度字段为 `null`。
看到应用启动成功或文件生成，不等于 cached data 被接受。

## 离线解析

先尝试 `0000.input.jsc`；如果输入仍采用私有 header，再尝试 normalized cache：

```bash
uv run python -m disassembler 12345/0000.normalized.jsc \
  --version 13.2.152.41 --snapshot-blob v8_context_snapshot.bin \
  --format json > /tmp/input.disasm.json
uv run python -m decompiler /tmp/input.disasm.json > /tmp/input.decompiled.js
```

文件名没有特殊语义，snapshot 按 read-only checksum 匹配。解析无 header 数据时必须
显式提供 `--version` 和 `--payload-offset 0`，详见[反汇编器](python-disassembler.md)。
raw 模式不能检查已被移除的 header，也不能修复 serializer/object layout 的不兼容。

## NODE_OPTIONS 被禁用时

部分 Electron 应用禁用 Node options 环境变量 fuse，导致拒绝 `--require` 或忽略
`NODE_OPTIONS`。不要把捕获脚本塞进 `.jsc`，它必须在 V8 消费缓存之前执行。

先尝试暂停主进程：

```powershell
$env:V8_CACHE_DUMP_DIR = "C:\tmp\v8-cache-dump"
& "C:\path\to\application.exe" --inspect-brk=9229
```

在 `chrome://inspect` 配置 `localhost:9229`，连接暂停的主进程，在控制台执行：

```javascript
require(String.raw`C:\src\v8asm\disassembler\capture_cached_data.cjs`)
```

成功后再恢复运行。该方案不修改安装包，但若 inspector 也被禁用，或缓存早于暂停点
被消费，就不可用。此时在**应用副本**的 JavaScript loader 中插入预加载：

```powershell
Copy-Item "C:\path\to\resources\app.asar" "C:\tmp\app.asar"
npx @electron/asar extract "C:\tmp\app.asar" "C:\tmp\app-unpacked"
rg -n "cachedData|new vm\.Script|Module\._extensions.*jsc" "C:\tmp\app-unpacked"
```

在 loader 导入或保存 `vm.Script` 引用之前加入：

```javascript
require(String.raw`C:\src\v8asm\disassembler\capture_cached_data.cjs`);
const vm = require("node:vm");
```

自己的应用优先从修改后的源码运行或重建。未启用 ASAR 完整性校验时，也可打包并
替换测试副本中的 archive：

```powershell
npx @electron/asar pack "C:\tmp\app-unpacked" "C:\tmp\app.asar"
Copy-Item "C:\path\to\application-directory" "C:\tmp\application-test" -Recurse
Copy-Item "C:\tmp\app.asar" `
  "C:\tmp\application-test\resources\app.asar" -Force
Remove-Item Env:NODE_OPTIONS -ErrorAction SilentlyContinue
$env:V8_CACHE_DUMP_DIR = "C:\tmp\v8-cache-dump"
& "C:\tmp\application-test\application.exe"
Get-ChildItem "C:\tmp\v8-cache-dump" -Recurse
```

不要覆盖原始应用。签名或 ASAR 完整性校验可能拒绝重打包，不能靠 repack 绕过；
应改用源码构建、可用的 inspector 或对应 Electron/V8 原生入口。

脚本只观察 `vm.Script`。通过 native addon 或其他 V8 API 消费的 cache，需要在实际
API 边界捕获。应用接受而离线工具仍无法解析时，应检查精确源码的私有布局改动，
不能通过尝试所有偏移来宣布格式已被识别。
