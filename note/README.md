# 项目文档

除根目录项目介绍外，维护文档统一放在这里。命令默认在仓库根目录执行；Python
命令通过 uv 环境运行。文档描述能力边界，不用历史跑分或旧 binary 证明当前兼容性。

## 使用

| 文档 | 内容 |
| --- | --- |
| [python-disassembler.md](python-disassembler.md) | `.jsc`、版本 profile、对象图和原始 payload |
| [decompiler.md](decompiler.md) | 源码恢复、语义边界、Atom 示例 |
| [checkversion.md](checkversion.md) | 版本哈希计算与多进程搜索 |
| [capture-cached-data.md](capture-cached-data.md) | 捕获应用接受的缓存、Windows、禁用 NODE_OPTIONS 时的处理 |
| [disassembly-schema.md](disassembly-schema.md) | 结构化 JSON 契约 |
| [cached-data-and-snapshot.md](cached-data-and-snapshot.md) | snapshot 选择、Electron、static roots 与原生 bypass |

## 开发

| 文档 | 内容 |
| --- | --- |
| [development.md](development.md) | 轻量工作流程、代码与文档维护约定 |
| [environment-and-build.md](environment-and-build.md) | uv、官方 V8 checkout、依赖同步、`-j10` 与缓存 |
| [semantic-fixtures.md](semantic-fixtures.md) | 可执行 JS 行为覆盖与 fixture 生成 |
| [validation.md](validation.md) | 按改动选择测试和 Node/Electron matrix |
| [TODO.md](TODO.md) | 尚未完成的特性与正确性工作 |

## 研究与实验

- [Ghidra 原型](ghidra.md)：暂停开发，仅保留实验入口和限制。
- [早期 V8 字节码研究原稿](archive/early-bytecode-research.md)：历史材料，不是当前操作指南。

原生补丁以 `v8patch/*.patch` 为准，不再维护容易与实际补丁脱节的手工复制代码指南。
自动生成的 matrix/round 报告属于运行产物，不与本目录的维护文档混在一起。
