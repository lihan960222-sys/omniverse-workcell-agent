import asyncio
import json
import os
import traceback
from pathlib import Path
from typing import get_args

import carb
import omni.ext
import omni.kit.app
import omni.ui as ui
import omni.usd
from aiohttp import web

from workcell_agent.bridge import JOBS, create_app
from workcell_agent.dispatch import Dispatcher
from workcell_agent.isaac_runtime import IsaacHost
from workcell_agent.models import Operation, OperationRequest
from workcell_agent.scene import SceneSession


PAGES = {
    "资产": (("读取场景", "inspect_scene"), ("转换 STEP", "convert_step"),
             ("导入 USD", "import_asset"), ("材质设置", "set_material")),
    "物理": (("物理参数", "set_physics"), ("环境检查", "environment")),
    "机构": (("创建关节", "create_joint"), ("几何特征", "query_features")),
    "运动": (("开始运动", "start_motion"), ("暂停", "pause_motion"),
             ("继续", "resume_motion"), ("终止", "stop_motion"),
             ("复位", "reset_motion"), ("运动状态", "motion_status")),
    "检查": (("资产检查", "validate_asset"), ("检查类别", "validation_rules"), ("静态干涉", "check_interference"),
             ("运动干涉", "check_motion")),
}

PARAMETERS = {
    "convert_step": {"source": ""},
    "import_asset": {"path": "", "prim_path": "/World/Imported"},
    "set_material": {"prim_paths": [], "color": [0.5, 0.5, 0.5], "roughness": 0.5},
    "set_physics": {"prim_path": "", "mass_kg": 1.0, "collision": "convexHull"},
    "create_joint": {"path": "/World/WorkcellJoint", "body0": None, "body1": "",
                     "kind": "revolute", "anchor_m": [0, 0, 0], "axis": [0, 0, 1],
                     "limits": [-1.57, 1.57]},
    "validate_asset": {},
    "start_motion": {"initial_positions": {}, "actions": []},
    "check_motion": {"initial_positions": {}, "actions": []},
}


class WorkcellExtension(omni.ext.IExt):
    def on_startup(self, ext_id):
        self._enabled = True
        self._accepting = False
        self._transitioning = False
        self._generation = 0
        self._wake = asyncio.Event()
        self._runner = None
        self._jobs = None
        self._session = None
        self._host = None
        self._task = None
        self._gui_tasks = set()
        self._window = None
        self._stage_subscription = None
        self._update_subscription = None
        self._status = "正在初始化"
        self._last_job_state = None
        self._context = omni.usd.get_context()
        self._operations = list(get_args(Operation))
        self._parameter_model = ui.SimpleStringModel("{}")
        self._result_model = ui.SimpleStringModel("")
        self._job_model = ui.SimpleStringModel("")
        self._locate_model = ui.SimpleStringModel("")
        try:
            self._build_window()
        except Exception:
            self._status = "GUI 创建失败，请查看 Kit 日志"
            carb.log_error("Workcell GUI 创建失败\n" + traceback.format_exc())
            raise
        self._stage_subscription = self._context.get_stage_event_stream().create_subscription_to_pop(
            self._on_stage_event, name="workcell.agent.stage")
        self._update_subscription = omni.kit.app.get_app().get_update_event_stream().create_subscription_to_pop(
            self._refresh, name="workcell.agent.ui")
        self._wake.set()
        self._task = asyncio.ensure_future(self._serve())
        self._task.add_done_callback(self._service_finished)

    async def _serve(self):
        try:
            project_dir = os.environ["WORKCELL_PROJECT_DIR"]
            if not project_dir.strip():
                raise ValueError("WORKCELL_PROJECT_DIR 不能为空")
            self._project_dir = Path(project_dir).expanduser().resolve()
            token = os.environ["WORKCELL_TOKEN"]
            worker = Path(os.environ["WORKCELL_WORKER_PYTHON"]).expanduser()
            if not worker.is_absolute() or not worker.is_file():
                raise ValueError("WORKCELL_WORKER_PYTHON 必须是现有 Python 可执行文件的绝对路径")
            if len(token) < 16:
                raise ValueError("WORKCELL_TOKEN 至少需要16个字符")
            port = int(os.environ.get("WORKCELL_PORT", "8765"))
            if not 1 <= port <= 65535:
                raise ValueError("WORKCELL_PORT 必须介于1和65535之间")
            self._address = f"http://127.0.0.1:{port}"
            while self._enabled:
                await self._wake.wait()
                self._wake.clear()
                await self._close_connection()
                if not self._enabled:
                    break
                generation = self._generation
                stage = self._context.get_stage()
                if self._transitioning or stage is None:
                    self._set_status("等待场景：请在 Isaac Sim 中新建或打开 USD")
                    continue
                self._session = SceneSession(stage, self._project_dir)
                self._host = IsaacHost(self._session)
                dispatcher = Dispatcher(self._session, self._host)
                application = create_app(dispatcher, token)
                application.middlewares.append(self._require_current_stage)
                self._jobs = application[JOBS]
                self._runner = web.AppRunner(application, shutdown_timeout=5)
                await self._runner.setup()
                await web.TCPSite(self._runner, "127.0.0.1", port).start()
                if not self._enabled or generation != self._generation or self._context.get_stage() != stage:
                    self._wake.set()
                    continue
                self._accepting = True
                self._set_status(f"连接就绪：{self._address}")
        finally:
            await self._close_connection()

    @web.middleware
    async def _require_current_stage(self, request, handler):
        if not self._accepting or self._session is None or self._context.get_stage() != self._session.stage:
            raise web.HTTPServiceUnavailable(text="场景正在切换，请重新读取 scene_revision")
        return await handler(request)

    def _service_finished(self, task):
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._set_status(f"服务失败：{type(error).__name__}: {error}")
            carb.log_error("Workcell 服务失败\n" + "".join(traceback.format_exception(error)))

    async def _close_connection(self):
        self._accepting = False
        runner, jobs, host, session = self._runner, self._jobs, self._host, self._session
        self._runner = self._jobs = self._host = self._session = None
        try:
            try:
                if jobs is not None:
                    await jobs.close()
            finally:
                if runner is not None:
                    await runner.cleanup()
        finally:
            try:
                if host is not None:
                    await host.close()
            finally:
                if session is not None:
                    session.close()

    def _on_stage_event(self, event):
        event_type = int(event.type)
        opening = {int(omni.usd.StageEventType.OPENING), int(omni.usd.StageEventType.CLOSING)}
        settled = {int(omni.usd.StageEventType.OPENED), int(omni.usd.StageEventType.CLOSED),
                   int(omni.usd.StageEventType.OPEN_FAILED)}
        if event_type in opening | settled:
            self._transitioning = event_type in opening
            self._generation += 1
            self._accepting = False
            if self._jobs is not None:
                for job_id in self._jobs.jobs:
                    self._jobs.cancel(job_id)
            self._set_status("场景正在切换，旧任务已取消")
            self._wake.set()

    def on_shutdown(self):
        self._enabled = False
        self._accepting = False
        self._stage_subscription = None
        self._update_subscription = None
        if self._jobs is not None:
            for job_id in self._jobs.jobs:
                self._jobs.cancel(job_id)
        for task in self._gui_tasks:
            task.cancel()
        self._wake.set()
        if self._window is not None:
            self._window.destroy()
            self._window = None

    def _build_window(self):
        self._window = ui.Window("Workcell Agent", width=660, height=820)
        self._page_frames = []
        self._page_buttons = []
        with self._window.frame:
            with ui.VStack(spacing=6):
                self._status_label = ui.Label(self._status, height=30, word_wrap=True)
                self._revision_label = ui.Label("scene_revision：等待场景", height=24)
                self._motion_label = ui.Label("运动：未开始", height=24)
                with ui.HStack(height=28, spacing=4):
                    for index, title in enumerate(PAGES):
                        button = ui.Button(title, clicked_fn=lambda i=index: self._show_page(i))
                        self._page_buttons.append(button)
                with ui.ZStack(height=72):
                    for index, actions in enumerate(PAGES.values()):
                        frame = ui.Frame(visible=index == 0)
                        self._page_frames.append(frame)
                        with frame:
                            with ui.VStack(spacing=4):
                                with ui.HStack(height=28, spacing=4):
                                    for label, operation in actions:
                                        ui.Button(label, clicked_fn=lambda op=operation: self._choose(op))
                                if index == 4:
                                    ui.Button("查看可用检查类别", height=28,
                                              clicked_fn=lambda: self._action(self._submit, "validation_rules", {}))
                with ui.HStack(height=28, spacing=4):
                    ui.Label("Operation", width=80)
                    self._operation_combo = ui.ComboBox(0, *self._operations)
                    ui.Button("读取选中对象", width=120,
                              clicked_fn=lambda: self._action(self._load_selection))
                ui.Label("操作参数 JSON", height=22)
                with ui.ScrollingFrame(height=190):
                    ui.StringField(self._parameter_model, multiline=True, height=180)
                with ui.HStack(height=28, spacing=4):
                    ui.Button("运行", clicked_fn=lambda: self._action(self._submit))
                    ui.Button("保存工程", clicked_fn=lambda: self._action(self._submit, "save_project", {}))
                    ui.Button("读取场景", clicked_fn=lambda: self._action(self._submit, "inspect_scene", {}))
                with ui.HStack(height=28, spacing=4):
                    ui.Label("任务 ID", width=65)
                    ui.StringField(self._job_model)
                    ui.Button("查询任务", width=90, clicked_fn=lambda: self._action(self._query_job))
                    ui.Button("取消任务", width=90, clicked_fn=lambda: self._action(self._cancel_job))
                with ui.HStack(height=28, spacing=4):
                    ui.Label("Prim 路径", width=65)
                    ui.StringField(self._locate_model)
                    ui.Button("定位问题对象", width=120, clicked_fn=lambda: self._action(self._locate))
                ui.Label("执行结果", height=22)
                with ui.ScrollingFrame():
                    ui.StringField(self._result_model, multiline=True, read_only=True)
        self._show_page(0)

    def _show_page(self, index):
        for current, frame in enumerate(self._page_frames):
            frame.visible = current == index
            self._page_buttons[current].selected = current == index

    def _choose(self, operation):
        self._operation_combo.model.get_item_value_model().set_value(self._operations.index(operation))
        self._parameter_model.set_value(json.dumps(PARAMETERS.get(operation, {}), ensure_ascii=False, indent=2))

    def _operation(self):
        return self._operations[self._operation_combo.model.get_item_value_model().as_int]

    def _parameters(self):
        parameters = json.loads(self._parameter_model.as_string)
        if not isinstance(parameters, dict):
            raise ValueError("操作参数必须是 JSON 对象")
        return parameters

    def _require_session(self):
        if not self._accepting or self._session is None or self._context.get_stage() != self._session.stage:
            raise RuntimeError("当前没有可操作的场景，请等待连接就绪")

    def _submit(self, operation=None, parameters=None):
        self._require_session()
        request = OperationRequest(operation=operation or self._operation(),
                                   parameters=self._parameters() if parameters is None else parameters,
                                   scene_revision=self._session.revision)
        task = asyncio.ensure_future(self._submit_async(request, self._session))
        self._gui_tasks.add(task)
        task.add_done_callback(self._gui_finished)

    async def _submit_async(self, request, session):
        self._require_session()
        if self._session is not session:
            raise RuntimeError("场景已经切换，请重新提交操作")
        record = self._jobs.submit(request)
        self._job_model.set_value(record["job_id"])
        self._last_job_state = None
        self._show_result(record)

    def _gui_finished(self, task):
        self._gui_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._show_result({"status": "failed", "error": f"{type(error).__name__}: {error}"})
            carb.log_error("Workcell 操作提交失败\n" + "".join(traceback.format_exception(error)))

    def _query_job(self):
        self._require_session()
        job_id = self._job_model.as_string.strip()
        if job_id not in self._jobs.jobs:
            raise ValueError("当前场景中没有这个任务 ID")
        self._show_result(self._jobs.jobs[job_id])

    def _cancel_job(self):
        self._require_session()
        job_id = self._job_model.as_string.strip()
        if job_id not in self._jobs.jobs:
            raise ValueError("当前场景中没有这个任务 ID")
        self._show_result(self._jobs.cancel(job_id))

    def _load_selection(self):
        self._require_session()
        paths = self._context.get_selection().get_selected_prim_paths()
        if not paths:
            raise ValueError("请在场景中选中对象")
        operation = self._operation()
        parameters = self._parameters()
        if operation == "set_material":
            parameters["prim_paths"] = paths
        elif operation == "set_physics":
            if len(paths) != 1:
                raise ValueError("物理参数需要选中一个部件")
            parameters["prim_path"] = paths[0]
        elif operation == "create_joint":
            if len(paths) not in {1, 2}:
                raise ValueError("创建关节需要选中一个或两个部件")
            parameters["body0"] = paths[0] if len(paths) == 2 else None
            parameters["body1"] = paths[-1]
        else:
            self._show_result({"selected_prim_paths": paths})
            self._locate_model.set_value(paths[0])
            return
        self._parameter_model.set_value(json.dumps(parameters, ensure_ascii=False, indent=2))
        self._locate_model.set_value(paths[0])

    def _locate(self):
        self._require_session()
        path = self._locate_model.as_string.strip()
        if not path or not self._session.stage.GetPrimAtPath(path):
            raise ValueError(f"场景中没有这个 Prim：{path}")
        self._context.get_selection().set_selected_prim_paths([path], True)

    def _action(self, function, *args):
        try:
            return function(*args)
        except Exception as error:
            self._show_result({"status": "failed", "error": f"{type(error).__name__}: {error}"})
            raise

    def _show_result(self, value):
        self._result_model.set_value(json.dumps(value, ensure_ascii=False, indent=2, default=str))

    def _set_status(self, status):
        self._status = status
        if self._window is not None:
            self._status_label.text = status

    def _refresh(self, event):
        revision = self._session.revision if self._session is not None else "等待场景"
        self._revision_label.text = f"scene_revision：{revision}"
        if self._host is not None:
            status = self._host.status
            self._motion_label.text = f"运动：{status['state']}  时间：{status['time_s']:.3f} s"
        else:
            self._motion_label.text = "运动：未开始"
        if self._jobs is not None:
            record = self._jobs.jobs.get(self._job_model.as_string.strip())
            if record is not None:
                state = (record["job_id"], record["status"])
                if state != self._last_job_state:
                    self._last_job_state = state
                    self._show_result(record)
