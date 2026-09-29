# V8 版本哈希搜索

Python 模块读取缓存头的版本哈希，也支持直接输入哈希或计算已知版本的哈希。
搜索属于 CPU 密集任务，使用多进程，默认最多四个 worker；按资源情况显式调整。
`checkversion/main.c` 仅保留作历史参考。

```bash
uv run python -m checkversion input.jsc
uv run python -m checkversion --hash 0x2b2c7714
uv run python -m checkversion --calculate 13.6.233.10
uv run python -m checkversion input.jsc -j 10
```

范围使用 `START:END`，不包含上界。已有版本线索时优先缩小范围：

```bash
uv run python -m checkversion input.jsc \
  --major-range 13:14 --minor-range 4:5 \
  --build-range 100:130 --patch-range 0:50
```

默认 major/minor 为 `0:20`，build 为 `0:500`，patch 为 `0:200`；实现区分
V8 12 之前的反向 fold 和 V8 12+ 的正向 fold。哈希命中只是候选版本，不能证明
embedder suffix、编译参数、对象布局或 snapshot 匹配；实际解析仍需这些证据。
