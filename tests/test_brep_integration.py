import json
import os
from pathlib import Path
import sys

import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from pxr import Gf, Usd, UsdGeom, UsdPhysics

from test_geometry import write_step
from workcell_agent.brep import register_schema, sdk_status, convert_step_brep
from workcell_agent.dispatch import Dispatcher
from workcell_agent.geometry import check_interference
from workcell_agent.models import OperationRequest, MaterialSpec, PhysicsSpec
from workcell_agent.scene import SceneSession
from workcell_agent.usd_ops import set_material, set_physics

register_schema()


def assembly(tmp_path):
    source = tmp_path / "assembly.stp"
    write_step(source, [BRepPrimAPI_MakeBox(10, 10, 10).Shape(), BRepPrimAPI_MakeCylinder(3, 10).Shape()],
               [(0, (0, 0, 0)), (0, (5, 0, 0)), (1, (30, 0, 0))])
    return source


def test_real_official_conversion_preserves_brep_and_interference(tmp_path):
    assert sdk_status()["installed"]
    result = convert_step_brep(assembly(tmp_path), tmp_path / "converted")
    stage = Usd.Stage.Open(result["usd_path"])
    assert result["brep_definition_count"] == 2
    assert result["part_count"] == 3
    for part in result["parts"]:
        brep = stage.GetPrimAtPath(part["prim_path"] + "/BRep")
        assert brep and brep.GetTypeName() == "BrepArray"
        assert brep.IsA(UsdGeom.Gprim)
        assert UsdGeom.Xformable(brep).GetOrderedXformOps()[0].Get() == Gf.Vec3f(0.001)
        assert len(brep.GetAuthoredAttributes()) > 10
    report = check_interference(Path(result["geometry_manifest"]))
    assert report["coverage"]["complete"]
    assert report["findings"][0]["common_volume_m3"] == pytest.approx(5e-7)


async def test_import_step_texture_physics_save(tmp_path):
    os.environ["WORKCELL_WORKER_PYTHON"] = sys.executable
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, "Z")
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.Xform.Define(stage, "/World")
    session = SceneSession(stage, tmp_path / "project")
    try:
        imported = await Dispatcher(session).execute(OperationRequest(
            operation="import_step", scene_revision=session.revision, parameters={"source": str(assembly(tmp_path))}))
        part = imported["parts"][0]["prim_path"]
        assert part.startswith("/World/Imported/")
        texture = tmp_path / "color.ppm"
        texture.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
        session.edit(session.revision, lambda current: set_material(current, MaterialSpec(prim_paths=[part], texture=str(texture))))
        session.edit(session.revision, lambda current: set_physics(current, PhysicsSpec(prim_path=part, mass_kg=1)))
        assert stage.GetPrimAtPath(part + "/Geometry").HasAPI(UsdPhysics.CollisionAPI)
        assert not stage.GetPrimAtPath(part + "/BRep").HasAPI(UsdPhysics.CollisionAPI)
        saved = Usd.Stage.Open(session.save()["path"])
        assert saved.GetPrimAtPath(part + "/BRep").GetTypeName() == "BrepArray"
        assert UsdGeom.PrimvarsAPI(saved.GetPrimAtPath(part + "/Geometry")).GetPrimvar("st").Get()
        report = await Dispatcher(session).execute(OperationRequest(operation="check_interference", parameters={
            "manifest": imported["geometry_manifest"], "asset_root": imported["asset_root"]}))
        assert report["coverage"]["complete"]
    finally:
        session.close()


def test_changed_brep_file_is_rejected(tmp_path):
    result = convert_step_brep(assembly(tmp_path), tmp_path / "converted")
    manifest_path = Path(result["geometry_manifest"])
    manifest = json.loads(manifest_path.read_text())
    definition = next(iter(manifest["definitions"].values()))
    brep = manifest_path.parent / definition["usd_brep_file"]
    brep.write_bytes(brep.read_bytes() + b"corrupted")
    with pytest.raises(ValueError, match="USD BRep.*SHA-256"):
        check_interference(manifest_path)
