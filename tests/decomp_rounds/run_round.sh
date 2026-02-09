#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROUND_DIR="$ROOT_DIR/tests/decomp_rounds"
CASE_DIR="$ROUND_DIR/cases"
OUT_DIR="$ROUND_DIR/out"
TMP_DIR="$ROUND_DIR/tmp"
BYTENODE_PATH="/home/aynakeya/.npm/_npx/ea56e60f3ac75570/node_modules/bytenode"

mkdir -p "$OUT_DIR" "$TMP_DIR"

source "$HOME/.nvm/nvm.sh"
nvm use 24.7.0 >/dev/null

if [[ ! -x "$ROOT_DIR/v8asm" ]]; then
  echo "v8asm not found at $ROOT_DIR/v8asm" >&2
  exit 1
fi
if [[ ! -f "$BYTENODE_PATH/package.json" ]]; then
  echo "bytenode cache not found at $BYTENODE_PATH" >&2
  exit 1
fi

for js in "$CASE_DIR"/*.js; do
  base="$(basename "$js" .js)"
  casedir="$OUT_DIR/$base"
  mkdir -p "$casedir"

  v8_jsc="$casedir/$base.v8asm.jsc"
  btn_jsc="$casedir/$base.bytenode.jsc"

  "$ROOT_DIR/v8asm" asm "$js" -o "$v8_jsc" >"$casedir/$base.v8asm.asm.log" 2>&1 || true
  node -e "const b=require(process.argv[1]); b.compileFile({filename: process.argv[2], output: process.argv[3]});" \
    "$BYTENODE_PATH" "$js" "$btn_jsc" >"$casedir/$base.bytenode.asm.log" 2>&1 || true

  for mode in v8asm bytenode; do
    in_jsc="$casedir/$base.$mode.jsc"
    dis_txt="$casedir/$base.$mode.disasm.txt"
    dis_err="$casedir/$base.$mode.disasm.err"
    dec_js="$casedir/$base.$mode.dec.l4.js"

    if [[ ! -f "$in_jsc" ]]; then
      echo "// input jsc not found: $in_jsc" >"$dec_js"
      continue
    fi

    if "$ROOT_DIR/v8asm" disasm "$in_jsc" >"$dis_txt" 2>"$dis_err"; then
      if ! python3 "$ROOT_DIR/decompiler/v8decompiler.py" "$dis_txt" --level 4 --runtime >"$dec_js" 2>"$casedir/$base.$mode.decompile.err"; then
        echo "// decompile failed for $dis_txt" >"$dec_js"
      fi
    else
      echo "// disasm failed for $in_jsc" >"$dec_js"
    fi
  done
done

python3 "$ROUND_DIR/analyze_round.py" "$OUT_DIR" >"$ROUND_DIR/summary.md"
echo "Done. Summary: $ROUND_DIR/summary.md"
