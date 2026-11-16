# Linux Codex 测试

将下面内容交给 Linux 上的 Codex，替换三个路径。目标环境为 Isaac Sim 6.1.0、Linux x86_64 和 NVIDIA RTX GPU；录制需要 FFmpeg 的 ffprobe。

```text
项目：<仓库绝对路径>
Isaac Sim：<安装绝对路径>
STP：<模型绝对路径>

请按照项目 README 安装依赖、配置 workcell MCP，并启动带界面的 Omniverse / Isaac Sim。
检查并安装 NVIDIA USD BRep，使用 import_step 导入上述 STP，转换成包含 BrepArray 和显示 Mesh 的 USD。
使用 auto_material 自动设置银灰色金属外观：颜色 [0.55,0.57,0.60]、金属度 0.8、表面粗糙度 0.3、opacity 1；动力学参数保持原值。
调用 record_video，录制 10 秒、1920×1080、30 fps 的模型环绕展示 MP4，然后保存 USD 工程。
每一步等待实际任务完成，检查模型数量、材质绑定、USD 保存结果和视频解码结果。执行失败时读取日志、修复并重试。
最后给我 USD 工程、MP4、验证记录的绝对路径，并明确报告尚未完成的检查。
```

新配置的 MCP 需要 Codex 加载后才能调用。安装后若当前会话没有 `workcell` 工具，重新打开同一项目的 Codex 会话，再发送上述 prompt；保持 Isaac Sim 与 MCP 使用相同 `WORKCELL_TOKEN`。

测试操作顺序：

1. `connection_status`，随后 `environment`、`inspect_scene`。
2. `usd_brep_status`；未安装时执行 `install_usd_brep` 并查询 `get_job` 至完成。若 `restart_required=true`，使用项目启动脚本重新启动应用。
3. 获取当前 `scene_revision`，执行 `import_step`，参数为 `source` 和未被占用的 `prim_path`。
4. 用返回的 `asset_root` 执行 `auto_material`；`prim_paths` 是路径列表。
5. 更新 `scene_revision`，执行 `record_video`，`prim_path` 使用 `asset_root`。
6. 更新 `scene_revision`，执行 `save_project`。结果中的 `path` 为工程入口，`video` 为 MP4。

所有 `submit_operation` 都返回任务标识，只有 `get_job.status=succeeded` 表示对应操作成功。自动视觉材质采用统一默认外观；已有明确零件分类时，可以对各组零件分别设置四项外观参数。
