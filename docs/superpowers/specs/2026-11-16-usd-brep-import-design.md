# USD BRep 安装、STEP 导入、视觉材质与视频

用户授权在现有 MCP 中加入安装 USD BRep、打开 STEP、转换 USD、视觉材质参数和展示视频的完整操作。继续使用 Linux Isaac Sim 6.1.0。

## 操作与数据

- `usd_brep_status` 查询官方转换器、固定源码版本与 omniSolid schema。
- `install_usd_brep` 在项目指定目录获取并构建官方 NVIDIA USD BRep。固定源码 commit `3fd5b9548d19aa8c12c29bc9637a96d42a06f8a5`，调用官方 prebuild/build 脚本。缓存、日志和结果保存在 `.work`。成功必须完成实际 BRep 转换自检。
- `convert_step_brep` 使用 OCP 读取 STEP 装配及其原始 BRep，调用官方 `occt_to_usd` 将各部件写成 `BrepArray`，在装配 USD 中引用这些数据。现有 Mesh 与 BRep 对应关系保留，几何计算继续使用已验证的 OCP。
- `import_step` 执行 USD BRep 转换后，将转换资产导入当前场景，返回场景版本、部件路径和几何清单。转换期间场景发生变化时拒绝导入；原场景与源 STEP 保留。
- `set_material` 支持颜色、金属度、表面参数与贴图。使用贴图时明确选择生成 box UV 或使用已有 UV；缺少、无效 UV 在对应位置报告错误。对实例执行纹理编辑时将目标实例转为可编辑内容。
- `auto_material` 接收对象列表，自动设置颜色、金属度、表面粗糙度和透明度；默认使用银灰色金属外观，动力学参数保持原值。
- `record_video` 根据模型包围盒布置环绕相机及灯光，调用官方 CaptureExtension 生成 MP4，用 ffprobe 解码验证帧数、尺寸和时长。录制结束恢复原相机并清理本次资源。

## 运行方式

Omniverse Extension 调用独立 Python 几何进程，几何进程调用官方转换器。启动脚本在任何场景打开前通过 PXR_PLUGINPATH_NAME 注册资源类型的 omniSolid schema；官方转换器的动态库留在独立进程。这样遵守上游 OpenUSD 25.11 的二进制兼容限制。

USD 中每个部件拥有 Mesh 与 BRep 引用。BRep 保持毫米几何，通过局部比例转为当前资产的米单位，并使用 guide purpose。碰撞配置只处理可碰撞的 Mesh/标准几何，静态检查识别已经关联的 BRep，拒绝几何内容变化后的旧映射。

## 涉及文件

新增 `brep.py` 与安装脚本；更新 models、worker、Dispatcher、MCP schema、材质函数、GUI 资产页面、Linux 安装/启动脚本、工作流 Skill、CI 与文档。现有直接 OCP 转换操作保持可调用。

## 验证

使用真实 STEP 装配、官方转换器和 OpenUSD 验证 BrepArray 内容、毫米/米比例、实例、导入、UV、材质、保存及干涉检查。检查缺少安装、文件损坏、无效输入、旧场景版本等错误。Windows 执行可运行的核心测试；Linux CI 构建官方转换器并执行完整转换测试。Isaac Sim 的 schema 注册与界面操作单独列入实际运行验收，执行结果据实记录。

## 官方依据

- https://github.com/NVIDIA-Omniverse/usd-brep/blob/main/tools/occt_to_usd/README.md
- https://github.com/NVIDIA-Omniverse/usd-brep/blob/main/BUILDING.md
- https://github.com/NVIDIA-Omniverse/usd-brep/blob/main/tools/pyproject/README.md
