#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROUND_DIR="$ROOT_DIR/tests/decomp_rounds"
CASE="${VERSION_MATRIX_CASE:-$ROUND_DIR/cases/01_arith.js}"
OUT_DIR="${VERSION_MATRIX_OUT:-$ROUND_DIR/version_matrix}"
BYTENODE_PATH="${ROUND_BYTENODE_PATH:-/home/aynakeya/.npm/_npx/ea56e60f3ac75570/node_modules/bytenode}"

DEFAULT_V8ASM_BINS=(
  "$ROOT_DIR/v8asm"
  "$ROUND_DIR/bin_cache/v8asm.10.2.node18.x64.release/v8asm"
  "$ROUND_DIR/bin_cache/v8asm.11.3.node20.x64.release/v8asm"
  "$ROUND_DIR/bin_cache/v8asm.12.4.node22.x64.release/v8asm"
  "$ROUND_DIR/bin_cache/v8asm.13.4.electron.x64.release/v8asm"
  "/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.11.9.x64.release/v8asm"
  "/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.12.4.x64.release/v8asm"
  "/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.12.9.x64.release/v8asm"
  "/home/aynakeya/workspace/tmp/v8test/v8/out/v8asm.13.4.x64.release/v8asm"
)
DEFAULT_NODE_VERSIONS=(18.20.8 20.20.2 22.17.0 24.7.0)
VERSION_MATRIX_STRICT="${VERSION_MATRIX_STRICT:-1}"
VERSION_MATRIX_REQUIRE_BINS="${VERSION_MATRIX_REQUIRE_BINS:-0}"
VERSION_MATRIX_REQUIRE_NODES="${VERSION_MATRIX_REQUIRE_NODES:-0}"
VERSION_MATRIX_FORCE_MISMATCH="${VERSION_MATRIX_FORCE_MISMATCH:-1}"
VERSION_MATRIX_REQUIRE_FORCE_MISMATCH="${VERSION_MATRIX_REQUIRE_FORCE_MISMATCH:-0}"
VERSION_MATRIX_USE_BIN_SNAPSHOT="${VERSION_MATRIX_USE_BIN_SNAPSHOT:-1}"
VERSION_MATRIX_SNAPSHOT_BLOB="${VERSION_MATRIX_SNAPSHOT_BLOB:-}"

gate_failures=()
gate_warnings=()
declare -A snapshot_blob_option_support_cache=()
declare -A snapshot_blob_forced_recovery_cache=()

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

v8asm_snapshot_blob_for() {
  local bin="$1"
  if [[ -n "$VERSION_MATRIX_SNAPSHOT_BLOB" ]]; then
    printf "%s" "$VERSION_MATRIX_SNAPSHOT_BLOB"
    return
  fi
  if [[ "$VERSION_MATRIX_USE_BIN_SNAPSHOT" == "1" ]]; then
    local bin_snapshot
    bin_snapshot="$(dirname "$bin")/snapshot_blob.bin"
    if [[ -f "$bin_snapshot" ]]; then
      printf "%s" "$bin_snapshot"
    fi
  fi
}

run_v8asm() {
  local bin="$1"
  shift
  local snapshot_blob
  snapshot_blob="$(v8asm_snapshot_blob_for "$bin")"
  if [[ -n "$snapshot_blob" ]] && v8asm_should_use_snapshot_blob "$bin" "$snapshot_blob" "$@"; then
    "$bin" --snapshot_blob "$snapshot_blob" "$@"
  else
    "$bin" "$@"
  fi
}

v8asm_args_request_force_incompatible() {
  local arg
  for arg in "$@"; do
    if [[ "$arg" == "--force-incompatible" || "$arg" == "--best-effort" ]]; then
      return 0
    fi
  done
  return 1
}

v8asm_should_use_snapshot_blob() {
  local bin="$1"
  local snapshot_blob="$2"
  shift 2
  if ! v8asm_binary_supports_snapshot_blob "$bin"; then
    return 1
  fi
  if v8asm_args_request_force_incompatible "$@"; then
    if [[ -n "$VERSION_MATRIX_SNAPSHOT_BLOB" ]]; then
      v8asm_binary_supports_forced_snapshot_recovery "$bin"
    else
      return 0
    fi
  else
    [[ -z "$VERSION_MATRIX_SNAPSHOT_BLOB" ]]
  fi
}

v8asm_binary_supports_snapshot_blob() {
  local bin="$1"
  if [[ -n "${snapshot_blob_option_support_cache[$bin]:-}" ]]; then
    [[ "${snapshot_blob_option_support_cache[$bin]}" == "yes" ]]
    return
  fi
  if grep -aq -- "--snapshot_blob" "$bin"; then
    snapshot_blob_option_support_cache[$bin]="yes"
    return 0
  fi
  snapshot_blob_option_support_cache[$bin]="no"
  return 1
}

v8asm_binary_supports_forced_snapshot_recovery() {
  local bin="$1"
  if [[ -n "${snapshot_blob_forced_recovery_cache[$bin]:-}" ]]; then
    [[ "${snapshot_blob_forced_recovery_cache[$bin]}" == "yes" ]]
    return
  fi
  if grep -aq -- "V8ASM_ALLOW_SNAPSHOT_VERSION_MISMATCH" "$bin"; then
    snapshot_blob_forced_recovery_cache[$bin]="yes"
    return 0
  fi
  snapshot_blob_forced_recovery_cache[$bin]="no"
  return 1
}

append_unique() {
  local value="$1"
  shift
  local -n target="$1"
  local existing
  for existing in "${target[@]}"; do
    if [[ "$existing" == "$value" ]]; then
      return
    fi
  done
  target+=("$value")
}

record_failure() {
  append_unique "$1" gate_failures
}

record_warning() {
  append_unique "$1" gate_warnings
}

has_crash_signature() {
  local file="$1"
  [[ -s "$file" ]] || return 1
  grep -Eiq \
    "Segmentation fault|SIGSEGV|SIGTRAP|Received signal|Trace/breakpoint trap|core dumped|Fatal error|FailureMessage|unreachable code|CHECK failed|DCHECK failed|AddressSanitizer|heap-use-after-free" \
    "$file"
}

check_crash_output() {
  local context="$1"
  shift
  local file
  for file in "$@"; do
    if has_crash_signature "$file"; then
      record_failure "$context emitted crash signature in $file"
    fi
  done
}

strict_disasm_status() {
  local bin="$1"
  local jsc="$2"
  local txt="$3"
  local err="$4"
  set +e
  run_v8asm "$bin" disasm "$jsc" >"$txt" 2>"$err"
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
  run_v8asm "$bin" disasm "$jsc" --force-incompatible >"$txt" 2>"$err"
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
  echo "- strict_gate: \`$VERSION_MATRIX_STRICT\`"
  echo "- force_mismatch_probe: \`$VERSION_MATRIX_FORCE_MISMATCH\`"
  echo "- require_force_mismatch: \`$VERSION_MATRIX_REQUIRE_FORCE_MISMATCH\`"
  echo "- use_bin_snapshot_blob: \`$VERSION_MATRIX_USE_BIN_SNAPSHOT\`"
  if [[ -n "$VERSION_MATRIX_SNAPSHOT_BLOB" ]]; then
    echo "- snapshot_blob_override: \`$VERSION_MATRIX_SNAPSHOT_BLOB\`"
  fi
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
    if [[ "$VERSION_MATRIX_REQUIRE_BINS" == "1" ]]; then
      record_failure "required v8asm binary is missing: $bin"
    else
      record_warning "v8asm binary is missing: $bin"
    fi
    continue
  fi

  version="$(run_v8asm "$bin" version)"
  build_args="$(run_v8asm "$bin" build-args | paste -sd ';' -)"
  work="$OUT_DIR/self-$label"
  mkdir -p "$work"
  jsc="$work/$case_base.jsc"
  dis="$work/$case_base.disasm.txt"
  dis_err="$work/$case_base.disasm.err"
  dec="$work/$case_base.dec.l4.js"
  dec_err="$work/$case_base.decompile.err"

  set +e
  run_v8asm "$bin" asm "$CASE" -o "$jsc" >"$work/$case_base.asm.log" 2>&1
  asm_code="$?"
  set -e
  asm_status="$(status_of "$asm_code")"
  check_crash_output "self $label asm" "$work/$case_base.asm.log"
  if [[ "$asm_code" == "0" ]]; then
    strict_status="$(strict_disasm_status "$bin" "$jsc" "$dis" "$dis_err")"
    check_crash_output "self $label strict disasm" "$dis_err" "$dis"
    if [[ "$strict_status" == "ok" ]]; then
      decompile="$(decompile_status "$dis" "$dec" "$dec_err")"
      check_crash_output "self $label decompile" "$dec_err"
    else
      decompile="n/a"
    fi
  else
    strict_status="n/a"
    decompile="n/a"
  fi
  echo "| $label | \`$bin\` | \`$version\` | \`$build_args\` | $asm_status | $strict_status | $decompile |" >>"$summary"
  if [[ "$asm_status" != "ok" ]]; then
    record_failure "self $label asm returned $asm_status"
  fi
  if [[ "$strict_status" != "ok" ]]; then
    record_failure "self $label strict disasm returned $strict_status"
  fi
  if [[ "$decompile" != "ok" ]]; then
    record_failure "self $label decompile returned $decompile"
  fi
done

{
  echo ""
  echo "## bytenode Cache Checked Against v8asm"
  echo ""
  echo "| node | node_v8 | v8asm_label | v8asm_version | numeric_match | pointer_match | force_policy | strict_disasm | force_disasm | decompile_force |"
  echo "|---|---:|---|---:|---:|---:|---|---:|---:|---:|"
} >>"$summary"

for node_version in "${node_versions[@]}"; do
  set +e
  nvm use "$node_version" >/dev/null
  nvm_code="$?"
  set -e
  if [[ "$nvm_code" != "0" ]]; then
    echo "| \`$node_version\` | n/a | all | n/a | n/a | n/a | n/a | n/a | n/a | n/a |" >>"$summary"
    if [[ "$VERSION_MATRIX_REQUIRE_NODES" == "1" ]]; then
      record_failure "required Node version is not installed: $node_version"
    else
      record_warning "Node version is not installed: $node_version"
    fi
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
  check_crash_output "bytenode $node_actual compile" "$btn_dir/$case_base.bytenode.asm.log"
  if [[ "$btn_code" != "0" ]]; then
    echo "| \`$node_actual\` | \`$node_v8\` | all | n/a | n/a | n/a | n/a | bytenode-fail:$btn_code | n/a | n/a |" >>"$summary"
    record_failure "bytenode compile failed for $node_actual with exit $btn_code"
    continue
  fi

  for bin in "${v8asm_bins[@]}"; do
    label="$(basename "$(dirname "$bin")")"
    if [[ "$bin" == "$ROOT_DIR/v8asm" ]]; then
      label="repo-v8asm"
    fi
    if [[ ! -x "$bin" ]]; then
      echo "| \`$node_actual\` | \`$node_v8\` | $label | missing | n/a | n/a | n/a | n/a | n/a | n/a |" >>"$summary"
      if [[ "$VERSION_MATRIX_REQUIRE_BINS" == "1" ]]; then
        record_failure "required v8asm binary is missing for bytenode check: $bin"
      else
        record_warning "v8asm binary is missing for bytenode check: $bin"
      fi
      continue
    fi
    version="$(run_v8asm "$bin" version)"
    build_args="$(run_v8asm "$bin" build-args | paste -sd ';' -)"
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
    run_v8asm "$bin" checkversion "$btn_jsc" >"$work/$case_base.checkversion.txt" 2>&1 || true
    check_crash_output "bytenode $node_actual $label checkversion" "$work/$case_base.checkversion.txt"
    strict_status="$(strict_disasm_status "$bin" "$btn_jsc" "$work/$case_base.strict.disasm.txt" "$work/$case_base.strict.disasm.err")"
    check_crash_output "bytenode $node_actual $label strict disasm" "$work/$case_base.strict.disasm.err" "$work/$case_base.strict.disasm.txt"
    force_policy="skip"
    if [[ "$numeric_match" == "yes" && "$pointer_match" == "yes" ]]; then
      force_policy="required"
      force_status="$(force_disasm_status "$bin" "$btn_jsc" "$work/$case_base.force.disasm.txt" "$work/$case_base.force.disasm.err")"
      check_crash_output "bytenode $node_actual $label force disasm" "$work/$case_base.force.disasm.err" "$work/$case_base.force.disasm.txt"
    elif [[ "$VERSION_MATRIX_FORCE_MISMATCH" == "1" && "$pointer_match" == "yes" ]]; then
      force_policy="probe:numeric-mismatch"
      force_status="$(force_disasm_status "$bin" "$btn_jsc" "$work/$case_base.force.disasm.txt" "$work/$case_base.force.disasm.err")"
      check_crash_output "bytenode $node_actual $label force disasm" "$work/$case_base.force.disasm.err" "$work/$case_base.force.disasm.txt"
    else
      if [[ "$numeric_match" != "yes" ]]; then
        force_status="skipped:numeric-mismatch"
      elif [[ "$pointer_match" == "no" ]]; then
        force_status="skipped:pointer-mismatch"
      else
        force_status="skipped:pointer-unknown"
      fi
    fi
    if [[ "$force_status" == "ok" ]]; then
      decompile="$(decompile_status "$work/$case_base.force.disasm.txt" "$work/$case_base.force.dec.l4.js" "$work/$case_base.force.decompile.err")"
      check_crash_output "bytenode $node_actual $label force decompile" "$work/$case_base.force.decompile.err"
    else
      decompile="n/a"
    fi
    echo "| \`$node_actual\` | \`$node_v8\` | $label | \`$version\` | $numeric_match | $pointer_match | $force_policy | $strict_status | $force_status | $decompile |" >>"$summary"
    if [[ "$force_policy" == "required" ]]; then
      if [[ "$force_status" != "ok" ]]; then
        record_failure "bytenode $node_actual vs $label should force successfully but returned $force_status"
      fi
      if [[ "$decompile" != "ok" ]]; then
        record_failure "bytenode $node_actual vs $label force decompile returned $decompile"
      fi
    elif [[ "$force_policy" == probe:* ]]; then
      if [[ "$force_status" != "ok" ]]; then
        if [[ "$VERSION_MATRIX_REQUIRE_FORCE_MISMATCH" == "1" ]]; then
          record_failure "bytenode $node_actual vs $label mismatch probe returned $force_status"
        else
          record_warning "bytenode $node_actual vs $label mismatch probe returned $force_status"
        fi
      fi
    elif [[ "$force_status" != skipped:* ]]; then
      record_failure "bytenode $node_actual vs $label should skip force but returned $force_status"
    fi
  done
done

{
  echo ""
  echo "## Gate Summary"
  echo ""
  echo "- warnings: ${#gate_warnings[@]}"
  for warning in "${gate_warnings[@]}"; do
    echo "  - $warning"
  done
  echo "- failures: ${#gate_failures[@]}"
  for failure in "${gate_failures[@]}"; do
    echo "  - $failure"
  done
} >>"$summary"

echo "Done. Summary: $summary"
if [[ "${#gate_failures[@]}" -gt 0 ]]; then
  printf "Gate failures:\n" >&2
  printf "  - %s\n" "${gate_failures[@]}" >&2
  if [[ "$VERSION_MATRIX_STRICT" == "1" ]]; then
    exit 1
  fi
fi
