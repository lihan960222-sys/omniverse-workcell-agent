# NVIDIA 官方 Skills 来源

获取日期：2026-11-16。

- 官方仓库：https://github.com/isaac-sim/IsaacSim
- 发布标签：`v6.1.0`
- 固定 commit：`7c206f75bdadd9e05fc457f19863ca4c3f0cb693`
- 上游路径：`skills/`
- 许可：五个 `SKILL.md` 均标注 `Apache-2.0`；完整上游许可保存在 `LICENSE`。
- 上游第三方声明：`THIRD_PARTY_NOTICE.md`。
- 获取方式：在项目 `.work/nvidia-skills` 中获取该 commit 的 Git sparse checkout，复制下列五个完整目录；保持官方文件内容。

| Skill | 当前项目用途 | 配套文件 |
| --- | --- | --- |
| [physics-simulation](physics-simulation/SKILL.md) | PhysX、刚体、碰撞形状、物理材质、关节驱动和状态读取 | `examples.md`、`scripts/prim_physics_setup.py` |
| [usd-articulation](usd-articulation/SKILL.md) | 关节结构与 Robot Schema | `scripts/apply_robot_schema.py`、`scripts/multi_arm_assembly.py`、`scripts/validate_articulation.py` |
| [usd-composition-architecture](usd-composition-architecture/SKILL.md) | USD 几何、材质、物理和配置文件组织 | 全部内容位于 `SKILL.md` |
| [usd-pipeline](usd-pipeline/SKILL.md) | USD 内容检查、尺寸、材质与部件放置 | `scripts/articulation_builder.py`、`scripts/measure_asset.py`、`scripts/place_assets.py` |
| [spatial-reasoning](spatial-reasoning/SKILL.md) | 单位、坐标变换、边界和空间检查 | `advanced.md`、`scripts/spatial.py` |

五个目录共 15 个官方文件。目录内的 Markdown 相对文件链接及 `usd-pipeline` 到 `spatial-reasoning` 的相对引用均随目录提供。原文提及的其他 Skill 可在 Linux 安装目录 `$ISAAC_SIM_DIR/skills/` 中按名称读取。

使用时设置 `ISAAC_SIM_DIR` 为 Isaac Sim 6.1.0 安装目录，`WORKSPACE_DIR` 为当前项目可写工作目录；需要 Isaac Lab 的操作另外设置 `ISAAC_LAB_DIR`。Codex 根据任务读取相应 `SKILL.md`，代码调用依据 6.1.0 API 和实际运行结果检查。

本地检查：17 个复制文件的 SHA256 与固定 commit checkout 一致；11 项相对文件引用存在；8 个 Python 文件通过 `compileall` 语法检查。依赖 Isaac Sim 的脚本尚未运行。

官方说明：[Isaac Sim 6.1.0 Agent Skills](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/development_tools/agent_skills.html)。
