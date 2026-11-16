#!/usr/bin/env bash
set -euo pipefail

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ "$(uname -s)" == Linux ]] || { printf '%s\n' '启动需要 Linux。' >&2; exit 1; }
: "${ISAAC_SIM_PATH:?请设置 ISAAC_SIM_PATH}"
: "${WORKCELL_TOKEN:?请设置 WORKCELL_TOKEN，至少包含 16 个字符}"
[[ ${#WORKCELL_TOKEN} -ge 16 ]] || { printf '%s\n' 'WORKCELL_TOKEN 长度不足。' >&2; exit 1; }
[[ -x "$ISAAC_SIM_PATH/isaac-sim.sh" && -x "$repo/.venv/bin/python" ]] || {
    printf '%s\n' '需要 Isaac Sim 安装目录和项目 .venv，请运行 install_linux.sh。' >&2; exit 1;
}
[[ -d "$repo/.work/kit-deps/pydantic" ]] || {
    printf '%s\n' '缺少 Kit 依赖，请运行 install_linux.sh。' >&2; exit 1;
}
project="${WORKCELL_PROJECT_DIR:-$repo/.work/project}"
mkdir -p "$project" "$repo/.work/temp"
export WORKCELL_PROJECT_DIR="$(cd -- "$project" && pwd -P)"
export WORKCELL_WORKER_PYTHON="$repo/.venv/bin/python"
export WORKCELL_URL='http://127.0.0.1:8765'
export WORKCELL_PORT=8765
export PYTHONPATH="$repo/src:$repo/.work/kit-deps"
export PYTHONNOUSERSITE=1
export TMPDIR="$repo/.work/temp"
export WORKCELL_ORIGINAL_LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"

exec env -u VIRTUAL_ENV "$ISAAC_SIM_PATH/isaac-sim.sh" \
    --ext-folder "$repo/extensions" --enable workcell.agent \
    --/exts/isaacsim.core.simulation_manager/default_engine=physx \
    --/exts/isaacsim.physics.newton/auto_switch_on_startup=false "$@"
