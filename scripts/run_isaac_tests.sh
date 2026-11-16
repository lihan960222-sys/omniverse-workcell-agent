#!/usr/bin/env bash
set -euo pipefail

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ "$(uname -s)" == Linux ]] || { printf '%s\n' 'Isaac Sim 验收需要 Linux。' >&2; exit 1; }
: "${ISAAC_SIM_PATH:?请设置 ISAAC_SIM_PATH}"
[[ -x "$ISAAC_SIM_PATH/python.sh" && -x "$repo/.venv/bin/python" ]] || {
    printf '%s\n' '请完成 Isaac Sim 和 install_linux.sh 的安装。' >&2; exit 1;
}
[[ -d "$repo/.work/kit-deps/pydantic" ]] || {
    printf '%s\n' '缺少 Kit 依赖，请运行 install_linux.sh。' >&2; exit 1;
}
mkdir -p "$repo/.work/temp" "$repo/.work/pip-cache" "$repo/.work/kit-test-deps"
export TMPDIR="$repo/.work/temp"
export PIP_CACHE_DIR="$repo/.work/pip-cache"
export PYTHONNOUSERSITE=1
export PXR_PLUGINPATH_NAME="$repo/src/workcell_agent/resources/omniSolid${PXR_PLUGINPATH_NAME:+:$PXR_PLUGINPATH_NAME}"
export WORKCELL_BREP_ROOT="${WORKCELL_BREP_ROOT:-$repo/.work/usd-brep-sdk}"
export PYTHONPATH="$repo/src:$repo/.work/kit-deps:$repo/.work/kit-test-deps"
export WORKCELL_WORKER_PYTHON="$repo/.venv/bin/python"
export WORKCELL_URL='http://127.0.0.1:8765'
export WORKCELL_PORT=8765
export WORKCELL_ORIGINAL_LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}"

# pytest 提供原始测试的装饰器和断言，异步调度由 Kit 负责。
env -u VIRTUAL_ENV "$ISAAC_SIM_PATH/python.sh" -m pip install --upgrade \
    -c "$repo/requirements.lock" --target "$repo/.work/kit-test-deps" 'pytest>=8,<9' 'pytest-asyncio>=1,<2'
exec env -u VIRTUAL_ENV "$ISAAC_SIM_PATH/python.sh" "$repo/scripts/isaac_tests.py" "$@"
