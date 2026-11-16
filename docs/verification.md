# 验证记录

日期：2026-11-16。当前 Windows Python 3.11.16，OpenUSD 25.11，cadquery-ocp 7.9.3.1.1，MCP SDK 1.30.0。

## 已执行

- 完整核心测试：84 项通过，运行时间 17.60 秒；实际 XML 保存在本机 `.work/core-tests.xml`。
- STEP 装配转换、实例、嵌套变换、单位与同源 BRep 几何映射。
- 相离、相切、相交、包含、包围盒候选筛选、几何容差和修改后重新检查。
- 材质、纹理相对引用、质量、关节局部坐标与驱动单位。
- 当前场景编辑、旧版本拒绝、重新建立会话后的保存、源子层修改在独立进程重新打开。
- 真实 HTTP 服务与 MCP 客户端进程调用，鉴权、请求重复处理、任务取消。
- 轨迹速度/加速度、动作依赖、无效参数拒绝与允许接触分类。
- Ruff、Python 编译、Shell 语法检查；Python wheel 和 source distribution 构建。
- core 环境检查返回 ready；本机 isaac 检查返回 unavailable 和非零退出码。
- 五个 NVIDIA 官方 Skill 的 17 个文件与固定上游版本哈希一致；配套引用和脚本检查；项目工作流 Skill 参考场景审阅。

## 需要目标环境

Linux Isaac Sim 中的 7 项运行测试和 1 项 Extension HTTP 验收尚未执行。GUI 显示与操作、实际关节运动、PhysX 接触、CCD、官方规则执行和完整 SimReady profile 均不能由本机核心测试推定通过。

GitHub Linux CI 的运行状态另由实际 workflow 记录确认。测试脚本、步骤和结果字段见 [linux-validation.md](linux-validation.md)。
