# Linux 验收

目标：Linux x86_64、Isaac Sim 6.1.0、Python 3.12、Kit 110.3.0、PhysX。需要符合 Isaac Sim 要求的 NVIDIA GPU 和驱动。本机 Windows 没有 Isaac Sim，以下运行检查尚未执行。

## 安装目录

`ISAAC_SIM_PATH` 指向包含 `python.sh`、`isaac-sim.sh` 的安装目录。执行 `bash scripts/install_linux.sh`：

安装使用 `requirements.lock` 中的固定版本。

- `.venv`：MCP、OpenUSD 25.11、OCP 和核心测试。
- `.work/kit-deps`：Isaac Sim 使用的 pydantic、aiohttp、jinja2、packaging 及其依赖。
- `.work/kit-test-deps`：验收时安装 pytest 和 pytest-asyncio。
- `.work/temp`：安装和测试产生的临时文件。

Kit 通过安装包自带的 USD 运行。安装脚本将外部几何依赖保存在 `.venv`，Extension 通过 `WORKCELL_WORKER_PYTHON` 启动几何进程。

## 自动验收

从仓库目录执行：

```bash
export ISAAC_SIM_PATH=/absolute/path/to/isaac-sim
bash scripts/install_linux.sh
.venv/bin/python -m pytest tests --ignore=tests/isaac --junitxml=.work/core-tests.xml
bash scripts/run_isaac_tests.sh
```

运行前关闭使用 `8765` 端口的 Isaac Sim。验收会创建独立项目和临时令牌，使用 `SimulationApp` 启动真实应用，再由官方 `omni.kit.test.AsyncTestSuite` 和 `AsyncTextTestRunner` 执行测试。`SimulationApp.run_coroutine` 持续推进 Kit 事件循环。原有 pytest 测试函数的断言和实际场景保留。[Kit 异步测试文档](https://docs.omniverse.nvidia.com/kit/docs/omni.kit.test/2.0.6/USAGE_PYTHON.html)；[SimulationApp API](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/py/source/extensions/isaacsim.simulation_app/docs/index.html)

| 检查 | 通过条件 |
| --- | --- |
| Extension 连接 | 实际 HTTP `/health` 请求通过令牌鉴权，返回场景版本 |
| 机构运动 | 示例滑台通过 PhysX Articulation 到达 0.1 m，误差不超过 0.002 m，支持复位 |
| 资产规则 | 官方 validator 返回实际执行规则，并保留 profile 覆盖状态 |
| 接触记录 | 滑台运动碰到障碍物，收到两个不同 prim 的真实 PhysX 接触事件 |
| 接触生命周期 | 滑台接触和退回分别产生 CONTACT_FOUND、CONTACT_LOST，报告保留事件顺序 |
| 运动状态 | 重复启动被拒绝，已有运动保持，暂停与继续有效 |
| 初始化取消 | 终止、复位和关闭能取消初始化，状态保持一致 |
| 报告保留 | 运动完成后的终止与复位保留已经生成的报告内容 |

运行器完成七个独立 IsaacHost 测试后，启用 workcell.agent 执行 Extension 连接测试，每个阶段独立持有场景会话。

默认测试执行超时 900 秒，可用 `--timeout 1200` 调整；应用启动时间另外计算。失败会终止后续测试，并保留场景和报告。结果目录 `.work/isaac-tests/<run-id>` 中 `result.json` 必须同时满足 `status: completed`、`passed: true`、`tests_run: 8`。停留在 `starting` 表示执行没有正常完成。

GitHub Actions 运行 Linux Python 3.12 下的 OpenUSD/OCP 核心测试。GPU 与 Isaac Sim 验收由上述脚本运行，CI 结果只代表已执行的核心项目。

## 诊断导出

执行 `.venv/bin/python scripts/collect_diagnostics.py`，收集真实核心环境版本、`.work/core-tests.xml` 是否存在，以及已有 Isaac 验收结果中的状态、数量和测试名称。添加 `--runtime` 时，通过 `WORKCELL_URL` 和 `WORKCELL_TOKEN` 连接当前本机 Extension，提交 `environment` 并查询实际任务结果。

诊断保存为 `.work/diagnostics/<run-id>/report.json`，格式使用 `schema_version: 1`。连接或解析失败会返回错误；环境不可用时保留诊断文件并返回非零状态。

## 用户场景验收

按照 README 启动 Extension 并配置 Codex，使用用户自己的 STEP：

1. 调用 `connection_status` 和 `environment`，检查运行版本。
2. `convert_step` 完成后检查 `geometry_manifest`、零件数量和单位；使用实际尺寸核对一个已知零件。
3. 导入 USD，设置材质、物理和 Joint；确认几何轴、质量、限位和动作过程。
4. 执行静态干涉检查，检查覆盖范围、参与零件和共同体积。
5. 执行动作、暂停、继续、终止和复位，核对实际位置及预期接触。
6. 打开 HTML/JSON 报告，核对零件路径、时间、单位、检查状态和未覆盖项。
7. 保存项目，关闭并重新打开，核对修改仍然保留。

GUI 显示、用户 STEP 和完整 profile 检查需要分别保存验收记录。自动测试成功只覆盖表格中列出的场景。
