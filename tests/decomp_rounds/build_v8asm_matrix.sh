#!/usr/bin/env bash
set -u -o pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
V8_TEST_ROOT="/home/aynakeya/workspace/tmp/v8test"
V8_ROOT="$V8_TEST_ROOT/v8"
PATCH_ROOT="$REPO_ROOT/v8patch"
REPORT_DIR="$REPO_ROOT/tests/decomp_rounds/build_matrix"
REPORT="$REPORT_DIR/summary.md"
BIN_CACHE_ROOT="$REPO_ROOT/tests/decomp_rounds/bin_cache"

# label|tag|patch|out_dir|gn_args
ROWS=(
  "10.2-node|10.2.154.26|v8asm-10.2.patch|out/v8asm.10.2.node18.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=false"
  "10.2-electron|10.2.154.4|v8asm-10.2.patch|out/v8asm.10.2.154.4.electron.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_embedder_string=\"-electron.0\""
  "10.8-node|10.8.168.25|v8asm-10.8.patch|out/v8asm.10.8.node.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=false v8_enable_sandbox=false"
  "10.8-electron|10.8.168.25|v8asm-10.8.patch|out/v8asm.10.8.electron.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_embedder_string=\"-electron.0\""
  "11.3-node|11.3.244.8|v8asm-11.3.patch|out/v8asm.11.3.node20.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=false"
  "11.3-electron|11.3.244.8|v8asm-11.3.patch|out/v8asm.11.3.244.8.electron.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_embedder_string=\"-electron.0\" v8_enable_static_roots=true"
  "11.4-node|11.4.183.14|v8asm-11.4.patch|out/v8asm.11.4.183.14.node.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=false v8_enable_static_roots=false"
  "11.4-electron|11.4.183.14|v8asm-11.4.patch|out/v8asm.11.4.183.14.electron.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_embedder_string=\"-electron.0\""
  "11.9-node|11.9.169.7|v8asm-11.9.patch|out/v8asm.11.9.169.7.node.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=false v8_enable_static_roots=false"
  "11.9-electron|11.9.169.7|v8asm-11.9.patch|out/v8asm.11.9.169.7.electron.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_embedder_string=\"-electron.0\" v8_enable_static_roots=true"
  "12.4-node|12.4.254.21|v8asm-12.4.patch|out/v8asm.12.4.node22.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=false"
  "12.4-electron|12.4.254.12|v8asm-12.4.patch|out/v8asm.12.4.254.12.electron.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_embedder_string=\"-electron.0\""
  "12.9-node|12.9.202.28|v8asm-12.9.patch|out/v8asm.12.9.202.28.node.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=false v8_enable_static_roots=false"
  "12.9-electron|12.9.202.28|v8asm-12.9.patch|out/v8asm.12.9.202.28.electron.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_embedder_string=\"-electron.0\" v8_enable_static_roots=true"
  "13.2-node|13.2.152.41|v8asm-13.2.patch|out/v8asm.13.2.152.41.node.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=false v8_enable_sandbox=false v8_enable_static_roots=false"
  "13.2-electron|13.2.152.41|v8asm-13.2.patch|out/v8asm.13.2.152.41.electron.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_enable_sandbox=true v8_embedder_string=\"-electron.0\" v8_enable_static_roots=true"
  "13.2-electron-nostaticroots|13.2.152.41|v8asm-13.2.patch|out/v8asm.13.2.152.41.electron.nostaticroots.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_enable_sandbox=true v8_embedder_string=\"-electron.0\" v8_enable_static_roots=false"
  "13.4-node|13.4.114.21|v8asm-13.4.patch|out/v8asm.13.4.114.21.node.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=false v8_enable_sandbox=false v8_enable_static_roots=false"
  "13.4-electron-staticroots|13.4.114.21|v8asm-13.4.patch|out/v8asm.13.4.114.21.electron.staticroots.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_enable_sandbox=true v8_embedder_string=\"-electron.0\" v8_enable_static_roots=true"
  "13.6-node|13.6.233.10|v8asm.patch|out/v8asm.13.6.node24.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=false v8_enable_sandbox=false v8_enable_static_roots=false"
  "13.6-electron|13.6.233.8|v8asm.patch|out/v8asm.13.6.electron.x64.release|is_debug=false v8_enable_object_print=true v8_enable_disassembler=true v8_enable_pointer_compression=true v8_embedder_string=\"-electron.0\""
)

usage() {
  cat <<'USAGE'
Usage: tests/decomp_rounds/build_v8asm_matrix.sh [label ...]

Builds the requested v8asm matrix rows. With no labels, builds every row.
Each row checks out the V8 tag, runs gclient sync --with_branch_heads --with_tags,
applies the matching patch with --3way --recount, runs gn gen, then builds
with autoninja -j10.
USAGE
}

selected() {
  local label="$1"
  if [ "${#REQUESTED_LABELS[@]}" -eq 0 ]; then
    return 0
  fi
  local wanted
  for wanted in "${REQUESTED_LABELS[@]}"; do
    if [ "$label" = "$wanted" ]; then
      return 0
    fi
  done
  return 1
}

append_report_row() {
  local label="$1"
  local tag="$2"
  local patch="$3"
  local out_dir="$4"
  local status="$5"
  local version="$6"
  local args="$7"
  printf '| `%s` | `%s` | `%s` | `%s` | %s | `%s` | `%s` |\n' \
    "$label" "$tag" "$patch" "$out_dir" "$status" "$version" "$args" >>"$REPORT"
}

dirty_paths() {
  {
    git diff --name-only --cached
    git diff --name-only
  } | sort -u
}

restore_patch_files() {
  mapfile -t changed < <(dirty_paths)
  if [ "${#changed[@]}" -gt 0 ]; then
    git restore --source=HEAD --staged --worktree -- "${changed[@]}"
  fi
}

bin_cache_dir_for() {
  local out_dir="$1"
  printf '%s/%s\n' "$BIN_CACHE_ROOT" "$(basename "$out_dir")"
}

copy_bin_cache() {
  local out_dir="$1"
  local cache_dir
  cache_dir="$(bin_cache_dir_for "$out_dir")"

  if [ -e "$cache_dir/v8_context_snapshot.bin" ]; then
    printf 'refusing to keep external v8_context_snapshot.bin in %s\n' "$cache_dir" >&2
    return 1
  fi

  mkdir -p "$cache_dir"
  cp "$out_dir/v8asm" "$cache_dir/v8asm"
  cp "$out_dir/icudtl.dat" "$cache_dir/icudtl.dat"
  cp "$out_dir/snapshot_blob.bin" "$cache_dir/snapshot_blob.bin"
  "$out_dir/v8asm" version >"$cache_dir/version.txt"
  "$out_dir/v8asm" build-args >"$cache_dir/build-args.txt"
}

run_row() {
  local row="$1"
  local label tag patch out_dir gn_args
  IFS='|' read -r label tag patch out_dir gn_args <<<"$row"

  if ! selected "$label"; then
    return 0
  fi

  printf '\n== %s ==\n' "$label"
  printf 'tag=%s patch=%s out=%s\n' "$tag" "$patch" "$out_dir"

  if ! git diff --quiet || ! git diff --cached --quiet; then
    printf 'dirty V8 checkout before %s\n' "$label" >&2
    append_report_row "$label" "$tag" "$patch" "$out_dir" "dirty-before" "" ""
    return 1
  fi

  if ! git checkout -q "$tag"; then
    append_report_row "$label" "$tag" "$patch" "$out_dir" "checkout-failed" "" ""
    return 1
  fi

  if ! gclient sync --with_branch_heads --with_tags; then
    append_report_row "$label" "$tag" "$patch" "$out_dir" "sync-failed" "" ""
    return 1
  fi

  if ! git diff --quiet || ! git diff --cached --quiet; then
    printf 'dirty V8 checkout after sync for %s\n' "$label" >&2
    append_report_row "$label" "$tag" "$patch" "$out_dir" "dirty-after-sync" "" ""
    return 1
  fi

  if ! git apply --3way --recount "$PATCH_ROOT/$patch"; then
    restore_patch_files || true
    append_report_row "$label" "$tag" "$patch" "$out_dir" "apply-failed" "" ""
    return 1
  fi

  local status="ok"
  if ! gn gen "$out_dir" --args="$gn_args"; then
    status="gn-failed"
  elif ! autoninja -j10 -C "$out_dir" v8asm; then
    status="build-failed"
  fi

  local version=""
  local args=""
  if [ "$status" = "ok" ]; then
    version="$("$out_dir/v8asm" version 2>&1 | tr '\n' ' ' | sed 's/[[:space:]]*$//')"
    args="$("$out_dir/v8asm" build-args 2>&1 | tr '\n' ';' | sed 's/;*$//')"
    if ! copy_bin_cache "$out_dir"; then
      status="cache-failed"
    fi
  fi

  restore_patch_files || return 1
  append_report_row "$label" "$tag" "$patch" "$out_dir" "$status" "$version" "$args"

  [ "$status" = "ok" ]
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

REQUESTED_LABELS=("$@")

mkdir -p "$REPORT_DIR"
{
  printf '# v8asm Build Matrix\n\n'
  printf '%s\n' "- v8_checkout: \`$V8_ROOT\`"
  printf '%s\n' "- bin_cache: \`$BIN_CACHE_ROOT\`"
  printf '%s\n' '- sync: `gclient sync --with_branch_heads --with_tags`'
  printf '%s\n\n' '- build: `autoninja -j10 -C <out> v8asm`'
  printf '| label | tag | patch | out | status | version | build args |\n'
  printf '|---|---:|---|---|---|---:|---|\n'
} >"$REPORT"

cd "$V8_TEST_ROOT" || exit 1
# shellcheck source=/home/aynakeya/workspace/tmp/v8test/start_env.md
source start_env.md
cd "$V8_ROOT" || exit 1

failures=0
for row in "${ROWS[@]}"; do
  if ! run_row "$row"; then
    failures=$((failures + 1))
  fi
done

printf '\nBuild matrix report: %s\n' "$REPORT"
if [ "$failures" -ne 0 ]; then
  printf 'build_matrix_failures=%s\n' "$failures" >&2
  exit 1
fi
printf 'build_matrix_ok=1\n'
