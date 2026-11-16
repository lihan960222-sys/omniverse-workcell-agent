# 工站智能体实施与验收清单

用户已授权开发与 GitHub 上传。采用 Superpowers 的调查、真实测试、实施、独立审查和完成前验证流程。

| 任务 | 代码入口 | 验收依据 |
| --- | --- | --- |
| 环境与版本 | compatibility.json、environment.py | Python 包、Isaac、Kit、扩展版本与 PhysX 引擎报告 |
| MCP 与任务 | models.py、bridge.py、mcp_server.py | 真实 HTTP/MCP 请求、鉴权、重复请求、旧场景版本拒绝 |
| STEP 与场景 | geometry.py、dispatch.py、scene.py | 真实 STEP 装配、单位、实例、当前 Stage、保存后独立进程读取 |
| 材质与物理 | usd_ops.py | 材质绑定、纹理相对路径、质量与驱动单位、实例 collider |
| 机构坐标 | usd_ops.py、geometry.py | 嵌套旋转、局部锚点、平面与圆柱特征 |
| 官方验证 | isaac_runtime.py | 真实规则注册与执行，保留官方报告 |
| 运动 | motion.py、isaac_runtime.py | 曲线约束、依赖关系、实际关节、取消与重新启动 |
| 干涉与报告 | geometry.py、isaac_runtime.py、reports.py | 相离、相切、相交、包含、真实接触、HTML 转义 |
| GUI 与 Skills | extensions/、skills/ | 五个页面与共享操作；工作流参考检查及官方 Skill 来源 |
| Linux 与发布 | scripts/、.github/workflows/tests.yml | 固定依赖、验收脚本、GitHub CI |

## 交付状态

- [x] 核查并固定 Linux 运行目标和真实 API。
- [x] 实现七项功能、MCP、Extension、GUI、报告与示例代码。
- [x] 编写并运行本机真实 STEP、USD、MCP、HTTP 和数学测试。
- [x] 保存 NVIDIA 五个官方 Skills、来源与许可证。
- [x] 编写并检验项目工作流 Skill 的必要操作说明。
- [x] 独立审查当前场景、文件保存和运动生命周期。
- [x] 编写 Linux 安装、启动、实际 Isaac 测试与 CI。
- [ ] 在 GitHub Linux CI 执行核心测试并记录结果。
- [ ] 在 Linux Isaac Sim 执行实际运动、接触与规则验收。
- [ ] 在真实 Isaac Sim GUI 执行人工操作验收。

当前机器没有 Isaac Sim。需要该运行环境的检查保持未验证；核心测试结果不能代替这些检查。最终交付证据记录于 `docs/verification.md`。
