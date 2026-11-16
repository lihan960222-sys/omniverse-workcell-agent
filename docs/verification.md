# 验证记录

日期：2026-11-16。当前 Windows Python 3.11.16，OpenUSD 25.11，cadquery-ocp 7.9.3.1.1，MCP SDK 1.30.0。

## 已执行

- 完整核心测试：93 项通过；实际 XML 保存在本机 `.work/core-tests.xml`。
- GitHub Ubuntu 24.04、Python 3.12 CI：87 项通过，0 项失败、错误或跳过。已验证代码 commit 为 `5672df51f12fb7743ab2d9877ba8c355ca8d3b5a`；[CI 运行记录](https://github.com/lihan960222-sys/omniverse-workcell-agent/actions/runs/43813301416)。该记录的 `core-test-results` artifact 提供原始 XML。新增视觉材质与录制接口的 Linux 核心测试等待当前提交执行。
- STEP 装配转换、实例、嵌套变换、单位与同源 BRep 几何映射。
- 相离、相切、相交、包含、包围盒候选筛选、几何容差和修改后重新检查。
- 材质、纹理相对引用、质量、关节局部坐标与驱动单位。
- 自动视觉材质的颜色、金属度、表面粗糙度、透明度及质量保持检查。
- Y/Z upAxis、不同场景时间单位下的环绕相机取景和重复资源清理。
- 当前场景编辑、旧版本拒绝、重新建立会话后的保存、源子层修改在独立进程重新打开。
- 真实 HTTP 服务与 MCP 客户端进程调用，鉴权、请求重复处理、任务取消。
- 轨迹速度/加速度、动作依赖、无效参数拒绝与允许接触分类。
- Ruff、Python 编译、Shell 语法检查；Python wheel 和 source distribution 构建。
- core 环境检查返回 ready；本机 isaac 检查返回 unavailable 和非零退出码。
- 五个 NVIDIA 官方 Skill 的 17 个文件与固定上游版本哈希一致；配套引用和脚本检查；项目工作流 Skill 参考场景审阅。

## 需要目标环境

官方 USD BRep 的 Linux 编译与三项实际转换验收正在 CI 中执行。

Linux Isaac Sim 中的 8 项运行测试和 1 项 Extension HTTP 验收尚未执行。GUI 显示与操作、实际 MP4 录制、关节运动、PhysX 接触、CCD、官方规则执行和完整 SimReady profile 均不能由本机核心测试推定通过。

测试脚本、步骤和结果字段见 [linux-validation.md](linux-validation.md)。
