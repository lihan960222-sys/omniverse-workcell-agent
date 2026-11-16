# Omniverse Workcell Agent

让 Codex 通过 MCP 操作 Linux 上的 Isaac Sim 6.1.0。项目包括 STEP 转换、材质、物理、运动机构、资产检查、运动设置和自主干涉检查。

| 功能 | 使用方式 |
| --- | --- |
| STEP 转换 | 安装 NVIDIA USD BRep，OCP 导入装配，官方转换器生成 BrepArray，同时保留显示 Mesh 和零件映射 |
| 材质外观 | 自动设置 USD Preview Surface 颜色、金属度、表面粗糙度和透明度 |
| 展示视频 | 自动布置相机和灯光，录制环绕模型的 MP4，检查尺寸、帧数和时长 |
| 物理参数 | 设置刚体、碰撞形状、质量和重力 |
| 运动机构 | 建立固定、转动、移动 Joint；查询平面和圆柱几何特征 |
| 资产检查 | 调用 Isaac Sim 资产规则，报告执行规则和覆盖范围 |
| 运动设置 | 速度、加速度、动作依赖和超时；开始、暂停、继续、终止、复位 |
| 干涉检查 | 静态 BRep 共同体积和距离；运动过程 PhysX 接触记录；HTML/JSON 报告 |

STEP 提供几何和装配关系。质量、关节用途和运动过程需要补充参数。完整 SimReady 合规状态需要对应 profile 的全部规则执行证据。

**验证范围：** OpenUSD、OCP、HTTP、MCP、材质参数和相机取景通过真实核心测试。官方 USD BRep 由独立 Linux CI 构建并执行实际文件转换。具体结果见 [验证记录](docs/verification.md)。Isaac Sim、GPU 运动、接触、GUI 和 MP4 录制尚未执行；[Linux 验收说明](docs/linux-validation.md)记录检查步骤。版本约定见 [compatibility.json](compatibility.json)。

**Linux 安装**

准备 Isaac Sim 6.1.0、Python 3.12、Codex CLI、Git、GCC/G++、Make、flock 和 FFmpeg。仓库目录使用没有空格的绝对路径。Ubuntu 可通过 `sudo apt-get install build-essential git util-linux ffmpeg python3.12-venv` 安装系统依赖。在仓库目录执行：

```bash
export ISAAC_SIM_PATH=/absolute/path/to/isaac-sim
bash scripts/install_linux.sh
export WORKCELL_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export WORKCELL_PROJECT_DIR="$PWD/.work/my-project"
codex mcp add workcell --env WORKCELL_TOKEN="$WORKCELL_TOKEN" \
  --env WORKCELL_URL=http://127.0.0.1:8765 -- "$PWD/.venv/bin/workcell-mcp"
bash scripts/start_linux.sh
```

启动脚本在本机 `127.0.0.1:8765` 建立连接。Codex 与 Isaac Sim 使用同一个令牌；重新生成令牌后，需要更新 Codex MCP 配置。[Codex MCP 配置文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

在 Codex 中输入：

> 使用 workcell，检查并安装 USD BRep，将 `/absolute/path/to/assembly.stp` 通过 import_step 转换并导入，使用 auto_material 设置银灰色金属外观，录制 10 秒、1080p、30 fps 的环绕展示视频，然后保存 USD 工程。等待每个任务实际完成，返回 USD、MP4 和验证结果。

完整测试 prompt 见 [Linux Codex 测试](docs/linux-test-prompt.md)。`install_usd_brep` 从固定官方源码构建并验证转换器，首次执行需要下载编译依赖。`usd_brep_status` 返回安装证据及 `restart_required`；通过启动脚本加载的 `omniSolid` schema 在打开场景前注册。

`auto_material` 默认颜色 `[0.55, 0.57, 0.60]`、金属度 `0.8`、表面粗糙度 `0.3`、透明度参数 `opacity=1`。四项均可指定，只影响外观。视频保存于工程的 `videos/<id>/`，录制结束恢复原相机并移除本次灯光和相机；`recording.json` 保留解码检查结果。

`check_interference`、`query_features` 的 `asset_root` 指向装配根路径，默认 `/World`。通过 `import_asset` 导入默认位置后，明确填写 `/World/Imported`。检查自动读取当前场景变换，并报告场景版本与检查期间的变化。

在 Linux 仓库目录安装工作流 Skills：

```bash
mkdir -p .agents/skills
cp -R skills/workcell-workflow skills/vendor/nvidia/*/ .agents/skills/
```

**运行验收**

```bash
.venv/bin/python -m pytest tests --ignore=tests/isaac --ignore=tests/test_brep_integration.py --junitxml=.work/core-tests.xml
bash scripts/install_usd_brep.sh
.venv/bin/python -m pytest tests/test_brep_integration.py
.venv/bin/python scripts/create_example.py
# 关闭正在运行的 Isaac Sim，释放 8765 端口。
bash scripts/run_isaac_tests.sh
```

Isaac Sim 验收包含 8 个运行测试和 1 个 Extension 连接测试，结果写入 `.work/isaac-tests/<run-id>/result.json`。失败返回非零状态；只在完成全部 9 项测试后记录通过。加入 `--gui` 可显示窗口。

**导出诊断**

```bash
.venv/bin/python scripts/collect_diagnostics.py
# 已启动 Extension，并设置相同的 WORKCELL_TOKEN 时：
.venv/bin/python scripts/collect_diagnostics.py --runtime
```

输出 `.work/diagnostics/<run-id>/report.json`，包含环境版本、核心测试报告路径和 Isaac 验收状态。`--runtime` 会向当前 Extension 提交环境检查并查询任务结果。诊断文件只保留测试状态和名称。

[几何算法与单位](docs/geometry.md) · [Linux 验收](docs/linux-validation.md) · [NVIDIA 官方 Skills](skills/vendor/nvidia)
