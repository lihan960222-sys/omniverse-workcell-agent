# Linux 运行环境与接口依据

核查日期：2026-11-16。目标环境为 Linux x86_64、Isaac Sim 6.1.0、Python 3.12、Kit SDK 110.3.0，使用 PhysX。官方提供该版本的 Linux 安装包；pip 安装要求 GLIBC 2.35 或以上。[下载](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/download.html)、[Python 环境](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/installation/install_python.html)

机器可读配置位于 `compatibility.json`。文件中的版本来自官方文档，实际 Linux 运行验证尚未执行。

启动时设置 `--/exts/isaacsim.core.simulation_manager/default_engine=physx` 和 `--/exts/isaacsim.physics.newton/auto_switch_on_startup=false`。初始化后使用 `SimulationManager.get_active_physics_engine()` 确认当前引擎；6.1.0 的 Newton 扩展默认启用启动时自动切换。[SimulationManager 配置](https://github.com/isaac-sim/IsaacSim/blob/7c206f75bdadd9e05fc457f19863ca4c3f0cb693/source/extensions/isaacsim.core.simulation_manager/config/extension.toml)、[Newton 配置](https://github.com/isaac-sim/IsaacSim/blob/7c206f75bdadd9e05fc457f19863ca4c3f0cb693/source/extensions/isaacsim.physics.newton/config/extension.toml)

## 配套扩展

| 扩展 | Isaac Sim 6.1.0 配套版本 | 用途 |
| --- | --- | --- |
| `omni.kit.converter.cad` | 209.5.2 | CAD 转换扩展集合 |
| `omni.kit.converter.hoops_core` | 512.0.0 | STEP 转换 |
| `omni.kit.converter.common` | 511.0.0 | CAD 参数与公共接口 |
| `omni.asset_validator.core` | 1.20.1 | 验证引擎与结果序列化 |
| `isaacsim.asset.validation` | 2.2.0 | SimReady 规则安装与注册 |
| `isaacsim.core.experimental.prims` | 1.10.8 | Articulation 控制与状态读取 |
| `omni.physx` | 110.3.2 | PhysX 仿真与接触事件 |

版本依据：[Isaac Sim 6.1.0 release notes](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/overview/release_notes.html)。扩展配置声明 `omni.usd`、`omni.ui`、`omni.timeline` 和 `omni.kit.uiapp`，由该 Isaac Sim 安装中的 Kit 依赖管理器解析配套版本；应用接口通过 `omni.kit.app` 模块调用。

## CAD 转换

项目转换使用独立 Python 环境中的 `cadquery-ocp==7.9.3.1.1` 和 `usd-core==25.11`。STEPCAFControl 读取装配，BRepMesh 生成三角面，BRepTools 保存同源 BRep；真实 STEP 测试验证装配实例、嵌套位置、单位和几何映射。算法与测试见 [geometry.md](geometry.md)。上表 CAD Converter 版本记录 Isaac Sim 配套信息，项目启动无需启用这些转换扩展。

## SimReady 检查

`isaacsim.asset.validation` 2.2.0 提供 `simready-validate`、`simready-foundation-tier-core` 和 `simready-foundation-tier-isaac`，规则注册到 `usd_validation_nvidia`。它们可由 `omni.asset_validator.core` 使用；涉及非相邻碰撞 Mesh 的规则需要真实 PhysX 运行环境。[Isaac Sim 6.1.0 验证扩展](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/py/source/extensions/isaacsim.asset.validation/docs/index.html)

项目明确声明 `omni.asset_validator.core` 与 `isaacsim.asset.validation` 两项依赖。执行时读取 `ValidationRulesRegistry.categories()` 和 `ValidationRulesRegistry.rules(category)`，核对请求的规则是否已经注册。调用 `ValidationEngine` 的 `validate_async(stage_or_path)`，保留全部 `Results`；导出使用官方 `export_json_file(path, results)` 或 `IssueJSONEncoder`。[Asset Validator 1.20.1 API](https://docs.omniverse.nvidia.com/kit/docs/asset-validator/1.20.1/source/extensions/omni.asset_validator.core/docs/api.html)

指定规则时创建 `ValidationEngine(init_rules=False)`，对获取的每个规则类调用 `engine.enable_rule(RuleClass)`。1.20.1 的官方教程提供了完整调用代码。[规则选择示例](https://docs.omniverse.nvidia.com/kit/docs/asset-validator/1.20.1/source/extensions/omni.asset_validator.core/docs/tutorial/index.html)

报告必须列出请求规则、执行规则、扩展版本及无法执行项。空规则集合和缺失规则需要报告错误。规则检查结果可以按所选范围解释；完整 SimReady profile 的通过状态需要对应 profile 的全部要求被执行。

## 运动控制

运行时使用 `from isaacsim.core.experimental.prims import Articulation`，通过场景中的 articulation 路径创建对象。根据 `dof_names` 查找目标自由度，使用 `set_dof_position_targets` 或 `set_dof_velocity_targets` 提交目标；实际进度通过 `get_dof_positions`、`get_dof_velocities` 获取。物理初始化后才能使用相应 tensor 数据。[6.1.0 公开接口](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/py/source/extensions/isaacsim.core.experimental.prims/config/python_api.html)

官方动作示例使用 `set_dof_position_targets(target, dof_indices=index)` 并持续推进仿真。项目根据实际关节状态判定到位，同时保留超时条件；暂停与继续不重建已经执行的动作。[6.1.0 运动示例](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/robot_setup_tutorials/tutorial_pickplace_example.html)

v6.1.0 官方 Skill 使用 `Articulation(path)` 创建对象，调用 `isaacsim.core.experimental.utils.app.play(commit=True)` 推进初始化，随后通过 `get_dof_positions().numpy()` 和 `get_dof_velocities().numpy()` 读取 Warp 数组。[官方 physics-simulation Skill](https://github.com/isaac-sim/IsaacSim/blob/7c206f75bdadd9e05fc457f19863ca4c3f0cb693/skills/physics-simulation/SKILL.md)

固定版本源码确认 `set_dof_position_targets(self, positions, *, indices=None, dof_indices=None)` 接受对象和自由度索引；省略索引表示处理全部对象或自由度。`get_dof_positions` 返回形状为 `(N, D)` 的 `wp.array`。初始化由 physics-ready 事件处理，读取前检查 `is_physics_tensor_entity_valid()`。[v6.1.0 Articulation 源码](https://github.com/isaac-sim/IsaacSim/blob/7c206f75bdadd9e05fc457f19863ca4c3f0cb693/source/extensions/isaacsim.core.experimental.prims/python/impl/articulation.py)

## 官方 Skills

项目保存了 IsaacSim `v6.1.0` 的五个完整 Skill 目录，来源固定到 commit `7c206f75bdadd9e05fc457f19863ca4c3f0cb693`：`physics-simulation`、`usd-articulation`、`usd-composition-architecture`、`usd-pipeline`、`spatial-reasoning`。文件位于 `skills/vendor/nvidia/`，包含配套脚本、引用文档、上游 LICENSE 和 THIRD_PARTY_NOTICE.md。来源与使用范围见该目录的 `SOURCE.md`。[6.1.0 Agent Skills 文档](https://docs.isaacsim.omniverse.nvidia.com/6.1.0/development_tools/agent_skills.html)

## PhysX 接触记录

对需要报告的刚体或 articulation 应用 `PhysxSchema.PhysxContactReportAPI`，保留 `get_physx_simulation_interface().subscribe_contact_report_events(callback)` 返回的订阅对象。回调接收 `contact_headers` 与 `contact_data`；通过 `PhysicsSchemaTools.intToSdfPath` 取得部件与 collider 路径。[官方 Python 接口用例](https://docs.omniverse.nvidia.com/dev-guide/latest/programmer_ref/physics/rb_physics.html)

通过 `ContactEventType(header.type).name` 记录 API 实际事件名称，包括 `CONTACT_FOUND`、`CONTACT_PERSIST`、`CONTACT_LOST` 及仿真时间。数据包含 position、normal、impulse、separation；按 header 的 `contact_data_offset` 与 `num_contact_data` 读取本次数据并立即复制到项目记录。零接触点的结束事件保存在 events 中。碰撞形状、碰撞过滤、接触阈值和仿真时间步都会影响记录范围。[接触数据定义](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/latest/extensions/runtime/source/omni.physx/docs/dev_guide/contact_reports.html)

该 Contact Reports 页面明确提示其中完整示例不能直接执行，应参考安装包中的 `contactReportDemo`。当前已核查订阅方式与数据字段，6.1.0 上的实际接触事件、单位和阈值仍需通过 Linux 集成测试确认。

## Linux 集成验收

1. 检查 Python、Isaac Sim、Kit 和扩展版本，并保存环境报告。
2. 用真实 STEP 装配运行转换；重新打开 USD，核对部件数量、单位、层级和材质。
3. 使用具有明确问题的真实 USD 运行指定规则，确认结果包含对应问题与对象路径。
4. 执行旋转关节与移动关节动作，检查实际位置、运动方向、限位和终止条件。
5. 在有接触与无接触的真实场景中运行 PhysX，核对事件、位置、时间和过滤规则。
6. 启动 Extension 并执行 GUI 参数编辑、开始、暂停、终止、复位和报告导出。

Windows 独立模块测试与 Linux CI 可以检查文件操作和确定性逻辑。Isaac Sim Extension、CAD 转换器、GUI 和 PhysX 的可用状态由上述真实运行结果确定。
