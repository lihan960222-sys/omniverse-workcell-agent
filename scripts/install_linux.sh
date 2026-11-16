#!/usr/bin/env bash
set -euo pipefail

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ "$(uname -s)" == Linux ]] || { printf '%s\n' '安装需要 Linux。' >&2; exit 1; }
: "${ISAAC_SIM_PATH:?请设置 ISAAC_SIM_PATH 为 Isaac Sim 6.1.0 安装目录}"
[[ -x "$ISAAC_SIM_PATH/python.sh" && -x "$ISAAC_SIM_PATH/isaac-sim.sh" ]] || {
    printf '%s\n' 'ISAAC_SIM_PATH 中需要 python.sh 和 isaac-sim.sh。' >&2; exit 1;
}
command -v python3.12 >/dev/null
mkdir -p "$repo/.work/temp" "$repo/.work/pip-cache" "$repo/.work/kit-deps"
export TMPDIR="$repo/.work/temp"
export PIP_CACHE_DIR="$repo/.work/pip-cache"
export PYTHONNOUSERSITE=1

python3.12 -m venv "$repo/.venv"
"$repo/.venv/bin/python" -m pip install -c "$repo/requirements.lock" -e "${repo}[usd,geometry,test]"
"$repo/.venv/bin/python" -m pip check

# Kit 使用自带 USD，运行依赖单独安装到项目目录。
export PYTHONPATH="$repo/src:$repo/.work/kit-deps"
env -u VIRTUAL_ENV "$ISAAC_SIM_PATH/python.sh" -c \
    'import sys; assert sys.version_info[:2] == (3, 12), sys.version'
env -u VIRTUAL_ENV "$ISAAC_SIM_PATH/python.sh" -m pip install --upgrade \
    -c "$repo/requirements.lock" --target "$repo/.work/kit-deps" \
    'pydantic>=2.11,<3' 'aiohttp>=3.12,<4' 'jinja2>=3.1,<4' 'packaging>=24,<27'
"$repo/.venv/bin/python" -m workcell_agent.environment --target core
printf '%s\n' '依赖安装完成。启动和验收命令见 README.md。'
