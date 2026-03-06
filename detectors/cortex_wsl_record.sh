#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PS_SCRIPT_SOURCE="${SCRIPT_DIR}/cortex_host_record.ps1"
PS_SCRIPT_WIN="$(wslpath -w "${PS_SCRIPT_SOURCE}")"

WINDOW_TITLE="${1:-Cortex IDE}"
DURATION_SEC="${2:-8}"
OUTPUT_ARG="${3:-}"
FINDING_ID="${4:-${FINDING_ID:-}}"
FPS="${FPS:-20}"
ACTIONS_JSON="${ACTIONS_JSON:-}"
ACTIONS_FILE="${ACTIONS_FILE:-${SCRIPT_DIR}/cortex_wsl_video_actions.json}"
STRICT_PROCESS_NAME="${STRICT_PROCESS_NAME:-${CORTEX_STRICT_PROCESS_NAME:-}}"
ACTIONS_ONLY="${ACTIONS_ONLY:-${CORTEX_ACTIONS_ONLY:-0}}"

to_windows_path_any() {
  local input_path="$1"
  local abs_path=""
  local parent=""
  local name=""
  local parent_win=""

  if [[ "$input_path" == [A-Za-z]:\\* ]]; then
    printf '%s\n' "$input_path"
    return 0
  fi

  if [[ "$input_path" = /* ]]; then
    abs_path="$input_path"
  else
    abs_path="${PWD}/${input_path}"
  fi

  if parent_win="$(wslpath -w "$abs_path" 2>/dev/null)"; then
    printf '%s\n' "$parent_win"
    return 0
  fi

  parent="$(dirname "$abs_path")"
  name="$(basename "$abs_path")"
  mkdir -p "$parent"
  parent_win="$(wslpath -w "$parent")"
  printf '%s\\%s\n' "$parent_win" "$name"
}

load_actions_json_for_finding() {
  local actions_file="$1"
  local finding_id="$2"
  if [[ -z "$finding_id" || ! -f "$actions_file" ]]; then
    return 0
  fi
  python3 - "$actions_file" "$finding_id" <<'PY'
import json
import sys
from pathlib import Path

actions_file = Path(sys.argv[1])
finding_id = sys.argv[2]
try:
    data = json.loads(actions_file.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)

actions = data.get(finding_id)
if actions is None:
    actions = data.get("_default")
if not isinstance(actions, list):
    sys.exit(0)
print(json.dumps(actions, separators=(",", ":")))
PY
}

win_userprofile="$(powershell.exe -NoProfile -Command '$env:USERPROFILE' | tr -d '\r' | tail -n 1)"
if [[ -z "${win_userprofile}" ]]; then
  echo "Failed to resolve Windows USERPROFILE from WSL." >&2
  exit 1
fi

# Stage recorder script into Windows TEMP so powershell.exe -File uses a native path.
win_temp_dir="$(powershell.exe -NoProfile -Command '$env:TEMP' | tr -d '\r' | tail -n 1)"
if [[ -n "${win_temp_dir}" ]] && wslpath -u "${win_temp_dir}" >/dev/null 2>&1; then
  temp_wsl_dir="$(wslpath -u "${win_temp_dir}")"
  mkdir -p "${temp_wsl_dir}"
  staged_ps_wsl="${temp_wsl_dir}/cortex_host_record.ps1"
  cp "${PS_SCRIPT_SOURCE}" "${staged_ps_wsl}"
  if staged_win="$(wslpath -w "${staged_ps_wsl}")"; then
    PS_SCRIPT_WIN="${staged_win}"
  fi
fi

if [[ -n "${OUTPUT_ARG}" ]]; then
  output_win="$(to_windows_path_any "${OUTPUT_ARG}")"
else
  ts="$(date +%Y%m%d-%H%M%S)"
  output_win="${win_userprofile}\\Videos\\cortex-${ts}.mp4"
fi

if [[ -z "${ACTIONS_JSON}" && -n "${FINDING_ID}" ]]; then
  ACTIONS_JSON="$(load_actions_json_for_finding "${ACTIONS_FILE}" "${FINDING_ID}")"
fi

args=(
  -NoProfile
  -ExecutionPolicy Bypass
  -File "${PS_SCRIPT_WIN}"
  -WindowTitle "${WINDOW_TITLE}"
  -OutputPath "${output_win}"
  -DurationSec "${DURATION_SEC}"
  -Fps "${FPS}"
  -InstallFfmpeg
)

if [[ -n "${STRICT_PROCESS_NAME}" ]]; then
  args+=(-ProcessName "${STRICT_PROCESS_NAME}")
fi

if [[ -n "${ACTIONS_JSON}" ]]; then
  args+=(-ActionsJson "${ACTIONS_JSON}")
fi

if [[ "${ACTIONS_ONLY}" == "1" ]]; then
  args+=(-ActionsOnly)
fi

powershell.exe "${args[@]}" | tr -d '\r'

echo "Windows output: ${output_win}"
if wslpath -u "${output_win}" >/dev/null 2>&1; then
  echo "WSL output: $(wslpath -u "${output_win}")"
fi
if [[ -n "${FINDING_ID}" ]]; then
  echo "Finding profile: ${FINDING_ID}"
fi
