# V8 字节码研究笔记

最后整理：2026-07-22。

这个目录只保存当前仍有效的研究结论和操作规则。过去按日期追加的实验日志已经
按主题合并；重复统计、已经被修复取代的临时结论、一次性调试输出不再保留。

## 阅读顺序

| 文档 | 内容 | 适合何时阅读 |
| --- | --- | --- |
| [environment-and-build.md](environment-and-build.md) | 官方 V8 环境、版本切换、patch、构建缓存 | 需要编译或更新原生 `v8asm` 时 |
| [cached-data-and-snapshot.md](cached-data-and-snapshot.md) | cached data、startup snapshot、static roots、Electron 兼容 | 遇到 header、checksum、`fixed_offset` 或 snapshot 报错时 |
| [python-disassembler.md](python-disassembler.md) | 纯 Python 反汇编器、profile、结构化 JSON、原始 payload | 需要解析 `.jsc` 或扩展版本支持时 |
| [decompiler.md](decompiler.md) | Python decompiler、结构恢复、安全边界、Atom 当前效果 | 需要改进伪代码质量时 |
| [validation.md](validation.md) | 单元测试、版本矩阵、Electron/Node 覆盖、证据等级 | 验证改动或判断一个版本是否真正受支持时 |

## 当前结论

1. 日常反汇编优先使用 `python3 -m disassembler`。它不初始化 V8，不会因为
   startup snapshot 或对象布局不匹配在进程启动阶段崩溃。
2. `.jsc` 本身并不总是包含 read-only heap 字符串。需要完整字符串时，应传入
   read-only checksum 匹配的 startup snapshot；文件名是
   `snapshot_blob.bin` 还是 `v8_context_snapshot.bin` 不能作为判断依据。
3. 原生 `v8asm` 仍然重要，但主要承担 V8 行为对照、self-cache 验证和
   Electron/Node 兼容性研究。`--force-incompatible` 只表示允许尝试，不表示
   对象布局已经兼容。
4. V8 兼容性必须同时考虑版本、cache magic、版本哈希、flags hash、RO checksum、
   pointer compression、sandbox、static roots 和 embedder。只看大版本或版本字符串
   都不够。
5. Python decompiler 默认运行完整源码恢复。数字 level 接口已经删除；需要逐条
   核对指令时使用 `--linear`。

## Atom 示例

仓库当前示例使用：

```bash
python3 -m disassembler example2/atom.compiled.dist.jsc \
  --version 13.4.114.21 \
  --snapshot-blob example2/v8_context_snapshot.bin \
  --format json > /tmp/atom.disasm.json

python3 -m decompiler /tmp/atom.disasm.json \
  > atom.compiled.dist.decompiled.current.js
```

这条路径完全由 Python 完成，不要求启动原生 V8。需要原生对照时，再按
[cached-data-and-snapshot.md](cached-data-and-snapshot.md) 中的 13.4 规则选择
匹配的 binary 和 snapshot。

## 维护规则

- 新结论直接更新对应主题文档，不再创建“某日验证记录”式笔记。
- 可变统计必须注明输入、命令和日期；不能把旧输出行数当成永久能力声明。
- 版本是否受支持以可执行验证为准，不以 patch 文件存在或旧 `out/` 目录存在为准。
- 一次性构建日志写入 `tests/decomp_rounds/*/summary.md`，不复制进这里。
- 不确定的对象、字符串或控制流必须保持占位符或低层形式，不能为了可读性猜测。
- 技术标识符、命令、路径和 V8 错误原文保留英文；解释正文统一使用中文。
