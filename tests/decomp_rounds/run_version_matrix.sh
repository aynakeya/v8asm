#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROUND_DIR="$ROOT_DIR/tests/decomp_rounds"
CASE="${VERSION_MATRIX_CASE:-$ROUND_DIR/cases/01_arith.js}"
OUT_DIR="${VERSION_MATRIX_OUT:-$ROUND_DIR/version_matrix}"
BYTENODE_PATH="${ROUND_BYTENODE_PATH:-/home/aynakeya/.npm/_npx/ea56e60f3ac75570/node_modules/bytenode}"

DEFAULT_V8ASM_BINS=(
  "$ROOT_DIR/v8asm"
  "/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.11.9.x64.release/v8asm"
  "/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.12.4.x64.release/v8asm"
  "/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.12.4.node22.x64.release/v8asm"
  "/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.12.9.x64.release/v8asm"
  "/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.13.4.x64.release/v8asm"
)
DEFAULT_NODE_VERSIONS=(22.17.0 24.7.0)

mkdir -p "$OUT_DIR"

source "$HOME/.nvm/nvm.sh"

case_base="$(basename "$CASE" .js)"
summary="$OUT_DIR/summary.md"

v8asm_bins=()
if [[ -n "${VERSION_MATRIX_V8ASM_BINS:-}" ]]; then
  # shellcheck disable=SC2206
  v8asm_bins=(${VERSION_MATRIX_V8ASM_BINS})
else
  v8asm_bins=("${DEFAULT_V8ASM_BINS[@]}")
fi

node_versions=()
if [[ -n "${VERSION_MATRIX_NODE_VERSIONS:-}" ]]; then
  # shellcheck disable=SC2206
  node_versions=(${VERSION_MATRIX_NODE_VERSIONS})
else
  node_versions=("${DEFAULT_NODE_VERSIONS[@]}")
fi

status_of() {
  local code="$1"
  if [[ "$code" == "0" ]]; then
    printf "ok"
  else
    printf "fail:%s" "$code"
  fi
}

strict_disasm_status() {
  local bin="$1"
  local jsc="$2"
  local txt="$3"
  local err="$4"
  set +e
  "$bin" disasm "$jsc" >"$txt" 2>"$err"
  local code="$?"
  set -e
  status_of "$code"
}

force_disasm_status() {
  local bin="$1"
  local jsc="$2"
  local txt="$3"
  local err="$4"
  set +e
  "$bin" disasm "$jsc" --force-incompatible >"$txt" 2>"$err"
  local code="$?"
  set -e
  status_of "$code"
}

decompile_status() {
  local txt="$1"
  local out="$2"
  local err="$3"
  set +e
  python3 "$ROOT_DIR/decompiler/v8decompiler.py" "$txt" --level 4 --runtime >"$out" 2>"$err"
  local code="$?"
  set -e
  status_of "$code"
}

build_arg_value() {
  local build_args="$1"
  local key="$2"
  printf "%s" "$build_args" | tr ';' '\n' | awk -F= -v k="$key" '$1 == k { print $2; found=1 } END { if (!found) print "unknown" }'
}

{
  echo "# V8/Node Cached-Data Matrix"
  echo ""
  echo "- case: \`$CASE\`"
  echo "- bytenode_path: \`$BYTENODE_PATH\`"
  if [[ -f "$BYTENODE_PATH/package.json" ]]; then
    bytenode_version="$(node -e "const p=require(process.argv[1] + '/package.json'); console.log(p.version || 'unknown')" "$BYTENODE_PATH")"
    echo "- bytenode_version: \`$bytenode_version\`"
  else
    echo "- bytenode_version: missing"
  fi
  echo ""
  echo "## v8asm Self-Generated Cache"
  echo ""
  echo "| label | bin | v8_version | build_args | asm | strict_disasm | decompile |"
  echo "|---|---|---:|---|---:|---:|---:|"
} >"$summary"

for bin in "${v8asm_bins[@]}"; do
  label="$(basename "$(dirname "$bin")")"
  if [[ "$bin" == "$ROOT_DIR/v8asm" ]]; then
    label="repo-v8asm"
  fi
  if [[ ! -x "$bin" ]]; then
    echo "| $label | \`$bin\` | missing | missing | n/a | n/a | n/a |" >>"$summary"
    continue
  fi

  version="$("$bin" version)"
  build_args="$("$bin" build-args | paste -sd ';' -)"
  work="$OUT_DIR/self-$label"
  mkdir -p "$work"
  jsc="$work/$case_base.jsc"
  dis="$work/$case_base.disasm.txt"
  dis_err="$work/$case_base.disasm.err"
  dec="$work/$case_base.dec.l4.js"
  dec_err="$work/$case_base.decompile.err"

  set +e
  "$bin" asm "$CASE" -o "$jsc" >"$work/$case_base.asm.log" 2>&1
  asm_code="$?"
  set -e
  asm_status="$(status_of "$asm_code")"
  if [[ "$asm_code" == "0" ]]; then
    strict_status="$(strict_disasm_status "$bin" "$jsc" "$dis" "$dis_err")"
    if [[ "$strict_status" == "ok" ]]; then
      decompile="$(decompile_status "$dis" "$dec" "$dec_err")"
    else
      decompile="n/a"
    fi
  else
    strict_status="n/a"
    decompile="n/a"
  fi
  echo "| $label | \`$bin\` | \`$version\` | \`$build_args\` | $asm_status | $strict_status | $decompile |" >>"$summary"
done

{
  echo ""
  echo "## bytenode Cache Checked Against v8asm"
  echo ""
  echo "| node | node_v8 | v8asm_label | v8asm_version | numeric_match | pointer_match | strict_disasm | force_disasm | decompile_force |"
  echo "|---|---:|---|---:|---:|---:|---:|---:|---:|"
} >>"$summary"

for node_version in "${node_versions[@]}"; do
  set +e
  nvm use "$node_version" >/dev/null
  nvm_code="$?"
  set -e
  if [[ "$nvm_code" != "0" ]]; then
    echo "| \`$node_version\` | n/a | all | n/a | n/a | n/a | n/a | n/a | n/a |" >>"$summary"
    continue
  fi
  node_actual="$(node -v)"
  node_v8="$(node -p 'process.versions.v8')"
  node_v8_numeric="${node_v8%%-*}"
  node_pointer_compression="$(node -p 'process.config.variables.v8_enable_pointer_compression ? "true" : "false"')"
  btn_dir="$OUT_DIR/bytenode-${node_actual#v}"
  mkdir -p "$btn_dir"
  btn_jsc="$btn_dir/$case_base.bytenode.jsc"
  set +e
  node -e "const b=require(process.argv[1]); b.compileFile({filename: process.argv[2], output: process.argv[3]});" \
    "$BYTENODE_PATH" "$CASE" "$btn_jsc" >"$btn_dir/$case_base.bytenode.asm.log" 2>&1
  btn_code="$?"
  set -e
  if [[ "$btn_code" != "0" ]]; then
    echo "| \`$node_actual\` | \`$node_v8\` | all | n/a | n/a | n/a | bytenode-fail:$btn_code | n/a | n/a |" >>"$summary"
    continue
  fi

  for bin in "${v8asm_bins[@]}"; do
    label="$(basename "$(dirname "$bin")")"
    if [[ "$bin" == "$ROOT_DIR/v8asm" ]]; then
      label="repo-v8asm"
    fi
    if [[ ! -x "$bin" ]]; then
      echo "| \`$node_actual\` | \`$node_v8\` | $label | missing | n/a | n/a | n/a | n/a | n/a |" >>"$summary"
      continue
    fi
    version="$("$bin" version)"
    build_args="$("$bin" build-args | paste -sd ';' -)"
    bin_pointer_compression="$(build_arg_value "$build_args" "v8_enable_pointer_compression")"
    numeric_match="no"
    if [[ "$node_v8_numeric" == "$version" ]]; then
      numeric_match="yes"
    fi
    pointer_match="unknown"
    if [[ "$bin_pointer_compression" == "true" || "$bin_pointer_compression" == "false" ]]; then
      pointer_match="no"
      if [[ "$bin_pointer_compression" == "$node_pointer_compression" ]]; then
        pointer_match="yes"
      fi
    fi
    work="$OUT_DIR/bytenode-${node_actual#v}-$label"
    mkdir -p "$work"
    "$bin" checkversion "$btn_jsc" >"$work/$case_base.checkversion.txt" 2>&1 || true
    strict_status="$(strict_disasm_status "$bin" "$btn_jsc" "$work/$case_base.strict.disasm.txt" "$work/$case_base.strict.disasm.err")"
    if [[ "$numeric_match" == "yes" && "$pointer_match" != "no" ]]; then
      force_status="$(force_disasm_status "$bin" "$btn_jsc" "$work/$case_base.force.disasm.txt" "$work/$case_base.force.disasm.err")"
    else
      if [[ "$numeric_match" == "yes" ]]; then
        force_status="skipped:pointer-mismatch"
      else
        force_status="skipped:numeric-mismatch"
      fi
    fi
    if [[ "$force_status" == "ok" ]]; then
      decompile="$(decompile_status "$work/$case_base.force.disasm.txt" "$work/$case_base.force.dec.l4.js" "$work/$case_base.force.decompile.err")"
    else
      decompile="n/a"
    fi
    echo "| \`$node_actual\` | \`$node_v8\` | $label | \`$version\` | $numeric_match | $pointer_match | $strict_status | $force_status | $decompile |" >>"$summary"
  done
done

echo "Done. Summary: $summary"
