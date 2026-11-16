import asyncio
import json
import logging
import math
from contextlib import suppress
from uuid import uuid4

import omni.kit.app
import omni.usd
import omni.timeline
import omni.physx
import omni.asset_validator.core as validator
from omni.physx.bindings._physx import ContactEventType
from pxr import UsdGeom, UsdPhysics, PhysxSchema, PhysicsSchemaTools
from isaacsim.core.experimental.prims import Articulation
from isaacsim.core.simulation_manager import SimulationManager

from .motion import MotionPlan, sample_motion, motion_duration, validate_motion, classify_contact
from .reports import write_report

logger = logging.getLogger(__name__)


class IsaacHost:
    def __init__(self, session):
        self.session = session
        self.timeline = omni.timeline.get_timeline_interface()
        self.status = {"state": "idle", "time_s": 0.0, "positions": {}}
        self.contacts = []
        self.contact_events = []
        self._step_subscription = None
        self._contact_subscription = None
        self._articulations = []
        self._dofs = {}
        self._plan = None
        self._started = {}
        self._completed = set()
        self._checking = False
        self._start_task = None
        self._finish_task = None
        self._control_lock = asyncio.Lock()
        self._closed = False

    @property
    def motion_running(self):
        return self.status["state"] in {"initializing", "running", "paused", "finishing"}

    def _positions(self):
        arrays = [art.get_dof_positions().numpy()[0] for art in self._articulations]
        return {path: float(arrays[group][index]) for path, (group, index) in self._dofs.items()}

    def _write_targets(self, targets):
        for group, articulation in enumerate(self._articulations):
            values = articulation.get_dof_position_targets().numpy().copy()
            for path, (owner, index) in self._dofs.items():
                if group == owner and path in targets:
                    values[0, index] = targets[path]
            articulation.set_dof_position_targets(values)

    async def start(self, parameters, checking=False):
        if self._closed:
            raise ValueError("运行服务已经关闭")
        if self.motion_running or self._control_lock.locked():
            raise ValueError("已有运动任务运行中")
        plan = MotionPlan.model_validate(parameters)
        validate_motion(plan)
        stage = self.session.stage
        if not math.isclose(UsdGeom.GetStageMetersPerUnit(stage), 1.0):
            raise ValueError("运动运行需要米制场景，请转换模型或明确设置正确的单位")
        if SimulationManager.get_active_physics_engine() != "physx":
            raise ValueError("当前运行引擎必须为 physx，请使用项目 Linux 启动脚本")
        if not any(prim.IsA(UsdPhysics.Scene) for prim in stage.Traverse()):
            raise ValueError("场景缺少 PhysicsScene")
        roots = [str(prim.GetPath()) for prim in stage.Traverse() if prim.HasAPI(UsdPhysics.ArticulationRootAPI)]
        if not roots:
            raise ValueError("场景缺少 ArticulationRootAPI")
        if checking:
            for rule in plan.allowed_contacts:
                for path in (rule.part_a, rule.part_b):
                    prim = stage.GetPrimAtPath(path)
                    if not prim or not (prim.HasAPI(UsdPhysics.RigidBodyAPI) or prim.HasAPI(UsdPhysics.CollisionAPI)):
                        raise ValueError(f"允许接触规则需要存在的刚体或碰撞对象: {path}")
        run_id = uuid4().hex
        self.status = {"run_id": run_id, "state": "initializing", "time_s": 0.0,
                       "positions": {}, "completed_actions": [], "contact_count": 0, "contact_event_count": 0}
        self._start_task = asyncio.current_task()
        self._checking = checking
        self._plan = plan
        self._started = {}
        self._completed = set()
        self.contacts = []
        self.contact_events = []
        self._finish_task = None
        try:
            if checking:
                for prim in stage.Traverse():
                    if prim.IsA(UsdPhysics.Scene):
                        physics = PhysxSchema.PhysxSceneAPI.Apply(prim)
                        physics.CreateTimeStepsPerSecondAttr(plan.physics_hz)
                        physics.CreateEnableCCDAttr(plan.enable_ccd)
                    if prim.HasAPI(UsdPhysics.RigidBodyAPI):
                        PhysxSchema.PhysxContactReportAPI.Apply(prim).CreateThresholdAttr(0)
                        PhysxSchema.PhysxRigidBodyAPI.Apply(prim).CreateEnableCCDAttr(plan.enable_ccd)
            self._articulations = [Articulation(path) for path in roots]
            self.timeline.play()
            async with asyncio.timeout(30):
                while True:
                    await omni.kit.app.get_app().next_update_async()
                    if self.status.get("run_id") != run_id or self.status["state"] != "initializing":
                        raise asyncio.CancelledError()
                    if all(art.is_physics_tensor_entity_initialized() and art.is_physics_tensor_entity_valid()
                           for art in self._articulations):
                        break
            self._dofs = {}
            for group, articulation in enumerate(self._articulations):
                for index, path in enumerate(articulation.dof_paths[0]):
                    self._dofs[str(path)] = (group, index)
            actual = self._positions()
            for action in plan.actions:
                if action.joint_path not in self._dofs:
                    raise ValueError(f"机构中没有目标自由度: {action.joint_path}")
                joint = stage.GetPrimAtPath(action.joint_path)
                factor = math.pi / 180 if joint.IsA(UsdPhysics.RevoluteJoint) else 1
                lower = joint.GetAttribute("physics:lowerLimit").Get()
                upper = joint.GetAttribute("physics:upperLimit").Get()
                if lower is not None and min(action.start, action.target) < lower * factor:
                    raise ValueError(f"动作低于关节下限: {action.id}")
                if upper is not None and max(action.start, action.target) > upper * factor:
                    raise ValueError(f"动作超过关节上限: {action.id}")
            for path, initial in plan.initial_positions.items():
                tolerances = [action.tolerance for action in plan.actions if action.joint_path == path]
                if path not in actual or (tolerances and abs(actual[path] - initial) > min(tolerances)):
                    raise ValueError(f"实际关节位置与计划起点不一致: {path}")
            self.status.update(state="running", positions=actual)
            if checking:
                self._contact_subscription = omni.physx.get_physx_simulation_interface().subscribe_contact_report_events(
                    self._on_contacts)
            self._step_subscription = omni.physx.get_physx_interface().subscribe_physics_step_events(self._step)
            directory = self.session.directory / "motions"
            directory.mkdir(exist_ok=True)
            plan_path = directory / f"{run_id}.json"
            plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
            self.status["motion_plan"] = str(plan_path)
            return dict(self.status)
        except asyncio.CancelledError:
            self._finalize(run_id, "cancelled")
            raise
        except Exception as error:
            if self.status.get("run_id") == run_id:
                self.status["error"] = f"{type(error).__name__}: {error}"
                self._finalize(run_id, "failed")
            raise
        finally:
            if self._start_task is asyncio.current_task():
                self._start_task = None

    def _step(self, dt):
        if self.status["state"] != "running":
            return
        try:
            self.status["time_s"] += float(dt)
            self.status["physics_dt_s"] = float(dt)
            actual = self._positions()
            self.status["positions"] = actual
            targets = {}
            for action in self._plan.actions:
                if action.id in self._completed or not set(action.depends_on) <= self._completed:
                    continue
                start = self._started.setdefault(action.id, self.status["time_s"])
                elapsed = self.status["time_s"] - start
                single = MotionPlan(initial_positions={action.joint_path: action.start},
                                    actions=[action.model_copy(update={"depends_on": []})])
                targets.update(sample_motion(single, elapsed))
                if elapsed >= motion_duration(single) and abs(actual[action.joint_path] - action.target) <= action.tolerance:
                    self._completed.add(action.id)
                elif elapsed > action.timeout:
                    raise TimeoutError(f"动作未在规定时间到位: {action.id}")
            self._write_targets(targets)
            self.status["completed_actions"] = sorted(self._completed)
            if len(self._completed) == len(self._plan.actions):
                self._request_finish("succeeded")
        except Exception as error:
            self.status["error"] = f"{type(error).__name__}: {error}"
            self._request_finish("failed")

    def _on_contacts(self, headers, data):
        if self.status["state"] not in {"running", "finishing"}:
            return
        for header in headers:
            a = str(PhysicsSchemaTools.intToSdfPath(header.actor0))
            b = str(PhysicsSchemaTools.intToSdfPath(header.actor1))
            event_type = ContactEventType(header.type)
            event = {"part_a": a, "part_b": b, "time_s": self.status["time_s"],
                     "type": event_type.name, "type_id": event_type.value,
                     "collider0": str(PhysicsSchemaTools.intToSdfPath(header.collider0)),
                     "collider1": str(PhysicsSchemaTools.intToSdfPath(header.collider1)),
                     "contact_count": int(header.num_contact_data)}
            event_index = len(self.contact_events)
            self.contact_events.append(event)
            if event_type == ContactEventType.CONTACT_LOST:
                continue
            for point in data[header.contact_data_offset:header.contact_data_offset + header.num_contact_data]:
                self.contacts.append({"part_a": a, "part_b": b, "time_s": event["time_s"],
                                      "event_index": event_index, "type": event["type"],
                                      "collider0": event["collider0"], "collider1": event["collider1"],
                                      "position_m": list(point.position), "normal": list(point.normal),
                                      "impulse_Ns": list(point.impulse), "separation_m": float(point.separation),
                                      "classification": classify_contact(self._plan, a, b, float(point.separation))})
        self.status["contact_count"] = len(self.contacts)
        self.status["contact_event_count"] = len(self.contact_events)

    def _request_finish(self, state):
        if self.status["state"] != "running":
            return
        self.status["state"] = "finishing"
        self._finish_task = asyncio.ensure_future(self._finish_after_callback(self.status["run_id"], state))

    async def _finish_after_callback(self, run_id, state):
        # 物理 callback 返回后才能解除订阅并保存报告。
        await asyncio.sleep(0)
        try:
            self._finalize(run_id, state)
        except Exception:
            logger.exception("运动任务结束处理失败")

    def _finalize(self, run_id, state):
        if self.status.get("run_id") != run_id or not self.motion_running:
            return
        self.status["state"] = "finishing"
        try:
            self._step_subscription = None
            self._contact_subscription = None
            self.timeline.pause()
            if self._checking:
                report = {"run": {**self.status, "state": state}, "findings": self.contacts,
                          "events": self.contact_events,
                          "coverage": {"method": "PhysX contacts", "trajectory_completed": state == "succeeded",
                                       "geometry": "authored collision approximations",
                                       "filters": "USD/PhysX collision pair filters apply",
                                       "static_static_checked": False,
                                       "physics_hz": self._plan.physics_hz,
                                       "enable_ccd": self._plan.enable_ccd,
                                       "allowed_contacts": [rule.model_dump() for rule in self._plan.allowed_contacts],
                                       "interpretation": "检查结果受碰撞形状、过滤规则和仿真步长影响"}}
                paths = write_report(report, self.session.directory / "reports" / run_id)
                self.status["reports"] = {key: str(value) for key, value in paths.items()}
            self.status["state"] = state
        except Exception as error:
            self.status.update(state="failed", error=f"{type(error).__name__}: {error}")
            raise

    async def _stop_active(self):
        if not self.motion_running:
            return
        run_id = self.status["run_id"]
        if self._start_task is not None:
            task = self._start_task
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if self._finish_task is not None:
            await asyncio.shield(self._finish_task)
        self._finalize(run_id, "cancelled")

    def _clear_motion(self):
        self._step_subscription = None
        self._contact_subscription = None
        self._checking = False
        self._plan = None
        self._articulations = []
        self._dofs = {}
        self._started = {}
        self._completed = set()
        self._finish_task = None
        self.contacts = []
        self.contact_events = []

    async def execute(self, operation, parameters):
        if operation == "get_selection":
            return {"paths": omni.usd.get_context().get_selection().get_selected_prim_paths()}
        if operation == "validation_rules":
            return {"categories": {category: [rule.__name__ for rule in validator.ValidationRulesRegistry.rules(category=category)]
                                   for category in validator.ValidationRulesRegistry.categories()},
                    "enabled_categories": list(validator.ValidationRulesRegistry.categories(enabledOnly=True)),
                    "validator_version": validator.get_version()}
        if operation == "validate_asset":
            categories = parameters.get("categories", list(validator.ValidationRulesRegistry.categories(enabledOnly=True)))
            engine = validator.ValidationEngine(init_rules=False)
            rules = []
            for category in categories:
                registered = validator.ValidationRulesRegistry.rules(category=category, enabledOnly="categories" not in parameters)
                if not registered:
                    raise ValueError(f"未注册验证类别: {category}")
                for rule in registered:
                    engine.enable_rule(rule)
                    rules.append(rule.__name__)
            if not rules:
                raise ValueError("规则集合为空")
            result = await engine.validate_async(self.session.stage)
            directory = self.session.directory / "reports" / uuid4().hex
            directory.mkdir(parents=True)
            output = directory / "official-validation.json"
            validator.export_json_file(output, result)
            report = {"categories": categories, "executed_rules": sorted(set(rules)),
                      "profile_conformance": "not_evaluated", "official_result": json.loads(output.read_text()),
                      "validator_version": validator.get_version()}
            report["reports"] = {key: str(value) for key, value in write_report(report, directory).items()}
            return report
        if operation in {"start_motion", "check_motion"}:
            return await self.start(parameters, operation == "check_motion")
        if operation == "motion_status":
            return dict(self.status)
        if operation == "pause_motion":
            if self.status["state"] != "running":
                raise ValueError("没有运行中的运动")
            self.timeline.pause()
            self.status["state"] = "paused"
        elif operation == "resume_motion":
            if self.status["state"] != "paused":
                raise ValueError("没有暂停的运动")
            self.status["state"] = "running"
            self.timeline.play()
        elif operation == "stop_motion":
            async with self._control_lock:
                await self._stop_active()
        elif operation == "reset_motion":
            async with self._control_lock:
                await self._stop_active()
                self.timeline.stop()
                self._clear_motion()
                self.status = {"state": "idle", "time_s": 0, "positions": {}}
        else:
            raise ValueError(f"未知运行操作: {operation}")
        return dict(self.status)

    async def close(self):
        self._closed = True
        async with self._control_lock:
            await self._stop_active()
            self._clear_motion()
