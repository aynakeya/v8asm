# Python V8 version-hash searcher

The Python implementation reads the version hash from a V8 cached-data file or
accepts a hash directly. Hash search is CPU-bound, so it uses worker processes
rather than threads. The default is at most four processes; use `-j 10`
explicitly when the machine has capacity.

`main.c` is retained as historical reference. The supported entry point is the
Python module.

```bash
python3 -m checkversion input.jsc
python3 -m checkversion --hash 0x2b2c7714
python3 -m checkversion --calculate 13.6.233.10
python3 -m checkversion input.jsc -j 10
```

Search ranges use an exclusive upper bound and can be narrowed when part of the
version is already known:

```bash
python3 -m checkversion input.jsc \
  --major-range 13:14 \
  --minor-range 4:5 \
  --build-range 100:130 \
  --patch-range 0:50
```

Defaults match the original C prototype: major/minor `0:20`, build `0:500`,
and patch `0:200`. The implementation handles both the pre-V8-12 reverse fold
and the V8-12+ forward fold.
