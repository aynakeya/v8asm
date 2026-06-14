#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROUND_DIR="$ROOT_DIR/tests/decomp_rounds"
CASE_DIR="$ROUND_DIR/cases"
OUT_DIR="$ROUND_DIR/out"
TMP_DIR="$ROUND_DIR/tmp"
V8ASM_BIN="${V8ASM_BIN:-$ROOT_DIR/v8asm}"
ROUND_NODE_VERSION="${ROUND_NODE_VERSION:-24.7.0}"
BYTENODE_PATH="${ROUND_BYTENODE_PATH:-/home/aynakeya/.npm/_npx/ea56e60f3ac75570/node_modules/bytenode}"

mkdir -p "$OUT_DIR" "$TMP_DIR"

source "$HOME/.nvm/nvm.sh"
nvm use "$ROUND_NODE_VERSION" >/dev/null

if [[ ! -x "$V8ASM_BIN" ]]; then
  echo "v8asm not found at $V8ASM_BIN" >&2
  exit 1
fi
if [[ ! -f "$BYTENODE_PATH/package.json" ]]; then
  echo "bytenode cache not found at $BYTENODE_PATH" >&2
  exit 1
fi

v8asm_version="$("$V8ASM_BIN" version)"
v8asm_build_args="$("$V8ASM_BIN" build-args)"
v8asm_pointer_compression="$(printf '%s\n' "$v8asm_build_args" | awk -F= '/^v8_enable_pointer_compression=/ {print $2}')"
node_version="$(node -v)"
node_v8_version="$(node -p 'process.versions.v8')"
node_v8_numeric="${node_v8_version%%-*}"
node_pointer_compression_raw="$(node -p 'String(process.config.variables.v8_enable_pointer_compression || 0)')"
node_sandbox_raw="$(node -p 'String(process.config.variables.v8_enable_sandbox || 0)')"
node_snapshot_raw="$(node -p 'String(process.config.variables.node_use_node_snapshot || false)')"
bytenode_version="$(node -e "const p=require(process.argv[1] + '/package.json'); console.log(p.version || 'unknown')" "$BYTENODE_PATH")"
if [[ "$node_pointer_compression_raw" == "1" || "$node_pointer_compression_raw" == "true" ]]; then
  node_pointer_compression="true"
else
  node_pointer_compression="false"
fi
if [[ "$node_v8_numeric" == "$v8asm_version" ]]; then
  compat_note="same numeric V8 version; Node/bytenode still use Node embedder snapshot/flags"
else
  compat_note="different numeric V8 version; bytenode mode is forced-incompatible research coverage"
fi

{
  echo "## Round Environment"
  echo "- v8asm_bin: \`$V8ASM_BIN\`"
  echo "- v8asm_version: \`$v8asm_version\`"
  echo "- v8asm_build_args:"
  printf '%s\n' "$v8asm_build_args" | sed 's/^/  - /'
  echo "- node_version: \`$node_version\`"
  echo "- node_v8_version: \`$node_v8_version\`"
  echo "- node_v8_enable_pointer_compression: \`$node_pointer_compression_raw\`"
  echo "- node_v8_enable_sandbox: \`$node_sandbox_raw\`"
  echo "- node_use_node_snapshot: \`$node_snapshot_raw\`"
  echo "- bytenode_path: \`$BYTENODE_PATH\`"
  echo "- bytenode_version: \`$bytenode_version\`"
  echo "- compatibility_note: $compat_note"
  echo ""
} >"$OUT_DIR/metadata.md"

for js in "$CASE_DIR"/*.js; do
  base="$(basename "$js" .js)"
  casedir="$OUT_DIR/$base"
  mkdir -p "$casedir"

  v8_jsc="$casedir/$base.v8asm.jsc"
  btn_jsc="$casedir/$base.bytenode.jsc"

  "$V8ASM_BIN" asm "$js" -o "$v8_jsc" >"$casedir/$base.v8asm.asm.log" 2>&1 || true
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

    "$V8ASM_BIN" checkversion "$in_jsc" >"$casedir/$base.$mode.checkversion.txt" 2>&1 || true

    disasm_args=()
    if [[ "$mode" == "bytenode" ]]; then
      disasm_args+=(--force-incompatible)
      if [[ -n "$v8asm_pointer_compression" && "$v8asm_pointer_compression" != "$node_pointer_compression" ]]; then
        {
          echo "// disasm skipped for $in_jsc"
          echo "// reason: v8asm pointer compression is $v8asm_pointer_compression, Node reports $node_pointer_compression"
        } >"$dec_js"
        {
          echo "Skipped bytenode force-disasm because pointer compression does not match."
          echo "v8asm_pointer_compression=$v8asm_pointer_compression"
          echo "node_pointer_compression=$node_pointer_compression"
        } >"$dis_err"
        continue
      fi
    fi

    if "$V8ASM_BIN" disasm "$in_jsc" "${disasm_args[@]}" >"$dis_txt" 2>"$dis_err"; then
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
