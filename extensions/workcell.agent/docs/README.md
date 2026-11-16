# Workcell Agent Extension

目标运行环境为 Linux、Isaac Sim 6.1.0。将本项目安装到 Isaac Sim 的 Python 环境，并启用 `workcell.agent`。

启动需要 `WORKCELL_PROJECT_DIR`、至少16个字符的 `WORKCELL_TOKEN`、指向独立几何计算 Python 的 `WORKCELL_WORKER_PYTHON`。`WORKCELL_PORT` 默认 `8765`。服务仅监听 `127.0.0.1`。

面板提供资产、物理、机构、运动和检查五个页面，共用 Operation 下拉菜单、JSON 参数和执行结果。选择功能按钮后填写参数，点击运行；任务 ID 可以用于查询或取消。物理、材质和关节操作支持读取场景选中对象。报告中的 Prim 路径可以填入定位区域并选中对应对象。检查页面可以显示已注册的验证类别。

GUI 与 HTTP 使用相同的 Dispatcher 和 JobManager。USD 操作由 Kit 主事件循环执行。场景打开或关闭时禁止新操作、取消旧任务，并关闭旧运行对象和场景会话；没有 Stage 时显示等待状态。启动错误记录到 Kit 日志及面板。

API 依据：[IExt](https://docs.omniverse.nvidia.com/kit/docs/kit-manual/latest/omni.ext/omni.ext.IExt.html)、[omni.ui](https://docs.omniverse.nvidia.com/kit/docs/omni.ui/latest/omni.ui.html)、[UsdContext](https://docs.omniverse.nvidia.com/kit/docs/omni.usd/latest/omni.usd/omni.usd.UsdContext.html)。当前 Windows 环境只能执行语法与配置检查，GUI 和场景切换需要 Isaac Sim 运行环境验证。
