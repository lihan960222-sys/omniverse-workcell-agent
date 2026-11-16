import asyncio
import json
import os
import shutil
import signal
from pathlib import Path
from uuid import uuid4

from pxr import Usd, UsdGeom, Sdf, Gf

from .environment import check_environment
from .models import MaterialSpec, PhysicsSpec, JointSpec, OperationRequest, StepImportSpec, AutoMaterialSpec
from .presentation import auto_material
from .reports import write_report
from .usd_ops import set_material, set_physics, create_joint


class Dispatcher:
    def __init__(self, session, host=None):
        self.session = session
        self.host = host

    async def _geometry_job(self, operation, parameters):
        python = os.environ.get("WORKCELL_WORKER_PYTHON")
        if not python or not Path(python).is_file():
            raise RuntimeError("WORKCELL_WORKER_PYTHON 必须指向安装了 geometry 依赖的 Python")
        folder = self.session.directory / "jobs" / uuid4().hex
        folder.mkdir(parents=True)
        revision = self.session.revision
        geometry_check = operation in {"check_interference", "query_features"}
        if geometry_check:
            if self.host and (self.host.motion_running or self.host.timeline.is_playing()):
                raise ValueError("静态几何检查需要停止并复位运动")
            snapshot = folder / "scene.usda"
            self.session.stage.Flatten().Export(str(snapshot))
            parameters = {**parameters, "stage_path": str(snapshot)}
        input_path = folder / "input.json"
        output_path = folder / "output.json"
        input_path.write_text(json.dumps(parameters, ensure_ascii=False), encoding="utf-8")
        environment = dict(os.environ)
        for key in ("PYTHONPATH", "PYTHONHOME", "PXR_PLUGINPATH_NAME", "LD_PRELOAD"):
            environment.pop(key, None)
        environment["LD_LIBRARY_PATH"] = environment.pop("WORKCELL_ORIGINAL_LD_LIBRARY_PATH", "")
        process = await asyncio.create_subprocess_exec(
            python, "-I", "-m", "workcell_agent.worker", operation, str(input_path), str(output_path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=environment,
            start_new_session=os.name != "nt")
        try:
            stdout, stderr = await process.communicate()
        except asyncio.CancelledError:
            if process.returncode is None:
                if os.name == "nt":
                    process.terminate()
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                await process.wait()
            raise
        (folder / "stderr.log").write_bytes(stderr)
        (folder / "stdout.log").write_bytes(stdout)
        if process.returncode:
            raise RuntimeError(f"几何任务失败，退出码 {process.returncode}: {stderr.decode(errors='replace')[-4000:]}")
        result = json.loads(output_path.read_text(encoding="utf-8"))
        if geometry_check:
            result["scene_revision"] = revision
            result["current_scene_revision"] = self.session.revision
            result["scene_changed_during_check"] = revision != self.session.revision
        if operation == "check_interference":
            result["reports"] = {key: str(value) for key, value in write_report(result, folder).items()}
        return result

    async def execute(self, request: OperationRequest):
        operation, parameters = request.operation, request.parameters
        if self.host and self.host.capture_running and operation not in {"environment", "inspect_scene", "get_selection"}:
            raise ValueError("视频录制期间请等待任务完成")
        if request.scene_revision:
            self.session.require_revision(request.scene_revision)
        if operation == "environment":
            return check_environment()
        if operation == "inspect_scene":
            return self.session.inspect()
        if operation in {"usd_brep_status", "install_usd_brep"}:
            if parameters:
                raise ValueError("USD BRep 安装与状态操作不接受参数")
            result = await self._geometry_job(operation, {})
            result["schema_registered"] = bool(Usd.SchemaRegistry().GetTypeFromSchemaTypeName("BrepArray"))
            result["restart_required"] = not result["schema_registered"]
            return result
        if operation == "import_step":
            spec = StepImportSpec.model_validate(parameters)
            if self.host and (self.host.motion_running or self.host.timeline.is_playing()):
                raise ValueError("导入 STEP 需要停止并复位运动")
            if not Usd.SchemaRegistry().GetTypeFromSchemaTypeName("BrepArray"):
                raise RuntimeError("请通过项目启动脚本重新启动 Omniverse，以注册 omniSolid schema")
            converted = await self.execute(OperationRequest(operation="convert_step_brep", parameters={"source": spec.source}))
            imported = await self.execute(OperationRequest(operation="import_asset", scene_revision=request.scene_revision,
                                                           parameters={"path": converted["usd_path"], "prim_path": spec.prim_path}))
            for part in converted["parts"]:
                part["prim_path"] = str(Sdf.Path(part["prim_path"]).ReplacePrefix(Sdf.Path("/World"), Sdf.Path(spec.prim_path)))
            return {**converted, **imported, "asset_root": spec.prim_path}
        if operation == "save_project":
            if self.host and self.host.motion_running:
                raise ValueError("保存工程需要停止并复位运动")
            return self.session.save()
        if operation == "auto_material":
            if self.host and (self.host.motion_running or self.host.timeline.is_playing()):
                raise ValueError("自动贴图需要停止并复位运动")
            spec = AutoMaterialSpec.model_validate(parameters)
            result = self.session.edit(request.scene_revision, lambda stage: auto_material(stage, spec))
            return {**result, "scene_revision": self.session.revision}
        methods = {"set_material": (MaterialSpec, set_material),
                   "set_physics": (PhysicsSpec, set_physics), "create_joint": (JointSpec, create_joint)}
        if operation in methods:
            if self.host and self.host.motion_running:
                raise ValueError("运动运行期间不能修改工程参数")
            model, function = methods[operation]
            spec = model.model_validate(parameters)
            if operation == "set_material" and spec.texture:
                source = Path(spec.texture).resolve(strict=True)
                directory = self.session.directory / "textures"
                directory.mkdir(exist_ok=True)
                target = directory / (uuid4().hex + source.suffix.lower())
                shutil.copy2(source, target)
                spec = spec.model_copy(update={"texture": str(target)})
            result = self.session.edit(request.scene_revision, lambda stage: function(stage, spec))
            return {**result, "scene_revision": self.session.revision}
        if operation == "import_asset":
            if self.host and self.host.motion_running:
                raise ValueError("运动运行期间不能导入资产")
            source = Path(parameters["path"]).resolve(strict=True)
            path = parameters.get("prim_path", "/World/Imported")
            target = Sdf.Path(path)
            if not target.IsAbsolutePath() or not target.IsPrimPath():
                raise ValueError("导入目标必须是绝对 Prim 路径")
            source_stage = Usd.Stage.Open(str(source))
            source_prim = source_stage.GetPrimAtPath(parameters["source_prim"]) if parameters.get("source_prim") else source_stage.GetDefaultPrim()
            if not source_prim:
                raise ValueError("USD 缺少有效 defaultPrim，请明确提供 source_prim")
            if UsdGeom.GetStageUpAxis(source_stage) != UsdGeom.GetStageUpAxis(self.session.stage):
                raise ValueError("源资产与目标场景的 upAxis 不同，需要明确转换方向")
            ratio = UsdGeom.GetStageMetersPerUnit(source_stage) / UsdGeom.GetStageMetersPerUnit(self.session.stage)
            if self.session.stage.GetPrimAtPath(path):
                raise ValueError("导入目标已存在")
            def author(stage):
                prim = UsdGeom.Xform.Define(stage, path).GetPrim()
                prim.GetReferences().AddReference(str(source), source_prim.GetPath())
                if ratio != 1:
                    UsdGeom.Xformable(prim).AddScaleOp(opSuffix="workcellUnits").Set(Gf.Vec3f(ratio))
                if not prim.GetPrimStack() or stage.GetCompositionErrors():
                    raise ValueError("USD 引用合成失败")
                return {"prim_path": path}
            result = self.session.edit(request.scene_revision, author)
            return {**result, "scene_revision": self.session.revision}
        if operation in {"convert_step", "convert_step_brep", "check_interference", "query_features"}:
            parameters = dict(parameters)
            if operation in {"convert_step", "convert_step_brep"}:
                source = Path(parameters["source"]).resolve(strict=True)
                parameters = {"source": str(source), "output_directory": str(
                    self.session.directory / "assets" / uuid4().hex)}
            return await self._geometry_job(operation, parameters)
        if not self.host:
            raise RuntimeError(f"{operation} 需要运行中的 Isaac Sim Extension")
        return await self.host.execute(operation, parameters)
