import json
import os
import sys
from pathlib import Path

import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from pxr import Gf, Usd, UsdGeom, UsdPhysics

from test_geometry import write_step
from workcell_agent.dispatch import Dispatcher
from workcell_agent.models import OperationRequest
from workcell_agent.scene import SceneSession


async def test_step_import_physics_and_live_interference(tmp_path):
    source = tmp_path / "装配 file.stp"
    write_step(source, [BRepPrimAPI_MakeBox(10, 10, 10).Shape()],
               [(0, (0, 0, 0)), (0, (20, 0, 0))])
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.SetStageUpAxis(stage, "Z")
    UsdGeom.Xform.Define(stage, "/World")
    session = SceneSession(stage, tmp_path / "project")
    dispatcher = Dispatcher(session)
    previous = os.environ.get("WORKCELL_WORKER_PYTHON")
    os.environ["WORKCELL_WORKER_PYTHON"] = sys.executable
    try:
        result = await dispatcher.execute(OperationRequest(operation="convert_step", parameters={"source": str(source)}))
        manifest_path = Path(result["geometry_manifest"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        await dispatcher.execute(OperationRequest(operation="import_asset", scene_revision=session.revision,
                                                  parameters={"path": result["usd_path"]}))
        paths = [part["prim_path"].replace("/World/", "/World/Imported/", 1) for part in manifest["parts"]]
        await dispatcher.execute(OperationRequest(operation="set_physics", scene_revision=session.revision,
                                                  parameters={"prim_path": paths[0], "mass_kg": 1}))
        assert stage.GetPrimAtPath(paths[0] + "/Geometry").HasAPI(UsdPhysics.CollisionAPI)
        parameters = {"manifest": str(manifest_path), "asset_root": "/World/Imported"}
        before = await dispatcher.execute(OperationRequest(operation="check_interference", parameters=parameters))
        assert before["findings"] == []
        UsdGeom.Xformable(stage.GetPrimAtPath(paths[1])).GetOrderedXformOps()[0].Set(
            Gf.Matrix4d().SetTranslate(Gf.Vec3d(0.005, 0, 0)))
        after = await dispatcher.execute(OperationRequest(operation="check_interference", parameters=parameters))
        assert after["coverage"]["complete"]
        assert after["findings"][0]["common_volume_m3"] == pytest.approx(5e-7)
        assert after["scene_revision"] == session.revision
        assert Path(after["reports"]["html"]).is_file()
        assert after["findings"][0]["part_a"].startswith("/World/Imported/")
    finally:
        session.close()
        if previous is None:
            os.environ.pop("WORKCELL_WORKER_PYTHON")
        else:
            os.environ["WORKCELL_WORKER_PYTHON"] = previous
