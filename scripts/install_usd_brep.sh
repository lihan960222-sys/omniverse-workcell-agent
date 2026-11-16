#!/usr/bin/env bash
set -euo pipefail

repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
    printf '%s\n' 'USD BRep 自动构建需要 Linux x86_64。' >&2; exit 1;
}
export WORKCELL_BREP_ROOT="${WORKCELL_BREP_ROOT:-$repo/.work/usd-brep-sdk}"
[[ "$WORKCELL_BREP_ROOT" = /* && "$WORKCELL_BREP_ROOT" != *[[:space:]]* ]] || {
    printf '%s\n' 'WORKCELL_BREP_ROOT 必须是没有空格的绝对路径。' >&2; exit 1;
}
for tool in git gcc g++ make flock; do command -v "$tool" >/dev/null; done
python="${WORKCELL_WORKER_PYTHON:-$repo/.venv/bin/python}"
[[ -x "$python" ]]
mkdir -p "$repo/.work/temp" "$repo/.work/packman" "$repo/.work/uv-cache"
export TMPDIR="$repo/.work/temp"
export PM_PACKAGES_ROOT="$repo/.work/packman"
export UV_CACHE_DIR="$repo/.work/uv-cache"
export PYTHONNOUSERSITE=1
unset PYTHONPATH PYTHONHOME PXR_PLUGINPATH_NAME LD_LIBRARY_PATH LD_PRELOAD VIRTUAL_ENV
exec 9>"$repo/.work/usd-brep-install.lock"
flock -n 9 || { printf '%s\n' 'USD BRep 安装任务正在运行。' >&2; exit 1; }
commit=3fd5b9548d19aa8c12c29bc9637a96d42a06f8a5
if [[ ! -d "$WORKCELL_BREP_ROOT" ]]; then
    git init "$WORKCELL_BREP_ROOT"
    git -C "$WORKCELL_BREP_ROOT" remote add origin https://github.com/NVIDIA-Omniverse/usd-brep.git
    git -C "$WORKCELL_BREP_ROOT" fetch --depth 1 origin "$commit"
    git -C "$WORKCELL_BREP_ROOT" switch --detach FETCH_HEAD
fi
[[ "$(git -C "$WORKCELL_BREP_ROOT" rev-parse HEAD)" == "$commit" ]] || {
    printf '%s\n' '安装目录的源码版本不符合项目配置。' >&2; exit 1;
}
cd -- "$WORKCELL_BREP_ROOT"
bash prebuild.sh
bash repo.sh build --release --target occt_to_usd -j 2
"$python" -m workcell_agent.brep verify-installation
