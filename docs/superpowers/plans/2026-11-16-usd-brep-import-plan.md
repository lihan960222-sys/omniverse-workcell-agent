# USD BRep 实施清单

依据：`docs/superpowers/specs/2026-11-16-usd-brep-import-design.md`。用户已经指定操作流程并授权补充功能。

1. 官方安装：固定源码版本，编写安装与状态检查。实际构建并对 OCP 生成的 box 执行官方转换，失败保留日志且返回非零状态。
2. 转换数据：编写真实转换测试；实现每个部件的 BrepArray 引用、单位处理、清单与内容验证；检查实例和静态干涉覆盖。
3. MCP：新增四个操作及参数定义；实现转换后导入与版本检查。通过真实 HTTP/MCP 调用测试。
4. 材质：编写真实 Mesh/纹理测试；实现 UV 生成、已有 UV 验证、实例处理与材质绑定。自动视觉设置使用颜色、金属度、表面粗糙度和透明度；确认动力学参数保持原值，保存后可重新读取。
5. Omniverse：更新 GUI、schema 注册、脚本、工作流 Skill 和实际 Isaac 测试。编译 Python，检查 Shell 语法与核心回归。
6. 视频：计算包围盒和环绕相机、布置灯光、调用官方 CaptureExtension 录制 MP4；ffprobe 解码检查帧数、尺寸和时长；完成与取消时清理资源。
7. 发布：独立审查，GitHub Linux CI 构建官方 SDK 并运行新增实际测试；记录实际结果并发布当前变更，提供 Linux Codex 测试 prompt。
