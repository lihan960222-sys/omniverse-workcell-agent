---
name: workcell-workflow
description: Use when Codex operates the workcell MCP tools for STEP/STP conversion, USD materials, physics, joints, motion, asset validation, or interference checks in Linux Isaac Sim.
---

# 工站操作

使用已连接的 `workcell` MCP。工具处理 Linux 本机路径。调用 `connection_status`、`environment` 和 `inspect_scene` 获取连接、依赖及对象路径；每项操作的参数通过 `operation_schema` 获取。

`submit_operation` 返回 `job_id`。使用 `get_job` 等待 `succeeded`、`failed` 或 `cancelled`；需要结果时读取 `result`。修改使用当前 `scene_revision`，重复提交同一请求时保持 `request_id` 与全部参数一致。

## STEP 到静态检查

1. `usd_brep_status` 查询官方 SDK，未安装时执行 `install_usd_brep` 并等待完成。`restart_required=true` 时通过项目启动脚本重新启动应用。
2. 查询 `motion_status`；存在运动时调用 `stop_motion`、`reset_motion`，每次修改前更新场景版本。
3. 读取最新场景版本，调用 `import_step`，`source` 使用 STEP 绝对路径，`prim_path` 明确指定装配位置，例如 `/World/Imported`。保留 `result.usd_path`、`result.geometry_manifest` 和 `result.asset_root`。
4. `check_interference` 的 `manifest` 使用转换结果；`asset_root` 使用实际导入位置。直接打开转换生成的 USD 时使用 `/World`。长度容差单位为 m，体积容差为 m³。
5. 等待任务完成，核对 `coverage.complete`、未映射对象清单、`scene_changed_during_check`，并再次获取当前版本，与报告的 `scene_revision` 比较。版本改变时重新检查。
6. 返回相交、接触数量及 `reports.html`、`reports.json`；同时说明未检查的对象和采用的容差。

检查使用任务开始时的场景。场景改变后，可取消正在运行的检查，待修改完成后重新提交。几何位置调整应作用于部件 Xform；当前工具没有移动部件操作。直接改变 Mesh 拓扑或叶节点 Geometry 的变换，会使原 BRep 映射失效。

只有 Mesh 且缺少对应 BRep/manifest 时，说明 CAD 精确检查无法执行，寻找原始 STEP 或完整转换目录。新增一份转换资产后，原场景中未映射的 Mesh 仍需要处理。`coverage.complete=false` 时报告部分覆盖。

## 参数与机构

| 操作 | 输入依据 |
| --- | --- |
| `set_material` | 用户指定的外观或现有资产数据；纹理文件会复制到工程 |
| `auto_material` | 对 `prim_paths` 设置颜色、金属度、表面粗糙度和透明度；仅影响外观 |
| `record_video` | `prim_path` 为展示模型根路径；默认 10 秒、1920×1080、30 fps，结果包含 MP4 和解码数据 |
| `set_physics` | `mass_kg` 必须来自已知质量；惯量使用 kg·m² |
| `query_features` | `manifest`、`asset_root`、当前 `prim_path`；返回世界坐标平面和圆柱特征 |
| `create_joint` | 已知机构关系、世界坐标 `anchor_m`、轴线、限位；配置 `articulation_root` |
| `validate_asset` | 先读 `validation_rules`；按当前已启用规则或指定类别执行 |
| `save_project` | 保存编辑层、USD 工程入口、工程 JSON 和运动配置索引 |

Joint 与 MotionPlan 的直线位置使用 m，旋转位置使用 rad；速度使用 m/s 或 rad/s，加速度使用 m/s² 或 rad/s²。Joint 的驱动输入使用 SI：直线 stiffness 为 N/m、damping 为 N·s/m、max_force 为 N；旋转分别为 N·m/rad、N·m·s/rad、N·m。质量、机构用途、驱动能力和工艺顺序无法仅从 STEP 确定，缺少这些数据时列出所需输入。运动时长不能直接作为完整生产节拍。

视觉展示按 `import_step`、`auto_material`、`record_video`、`save_project` 执行。每次修改前读取最新场景版本。视频需要停止运动和活动 Viewport，运行期间等待完成。报告视频的实际路径、帧数、时长和尺寸；完成外观设置后，物理参数保持原值。

## 运动与检查

`start_motion` 或 `check_motion` 的 job 成功表示启动完成。保存 `result.run_id`，持续提交 `motion_status`，等待该 run 的 `result.state` 进入终态。`paused` 表示仍需继续；`failed` 和 `cancelled` 分别报告原因。只有实际状态 `succeeded` 表示动作完成。

`check_motion` 使用 PhysX 接触记录。`allowed_contacts` 需要具体对象、允许穿透量与工程原因；`physics_hz` 和 `enable_ccd` 控制检查设置。读取最终报告的 `trajectory_completed`、接触分类、碰撞近似、过滤条件和时间步。动作完成与无干涉分别判断，当前检查覆盖已执行的轨迹和已启用的碰撞对。

资产验证保留官方逐条结果及执行规则。`profile_conformance=not_evaluated` 时，完整 SimReady 合规状态保持未评价。

遇到具体 USD 组织、物理、Articulation 或空间问题时，按需读取已安装的 NVIDIA `usd-composition-architecture`、`usd-pipeline`、`physics-simulation`、`usd-articulation`、`spatial-reasoning` Skills。接口以本项目固定版本和工具实际返回值为准。
