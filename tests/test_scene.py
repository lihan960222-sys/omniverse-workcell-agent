from pathlib import Path

import pytest
from pxr import Usd, UsdGeom, Gf

from workcell_agent.scene import SceneSession
from workcell_agent.models import MaterialSpec, PhysicsSpec, JointSpec
from workcell_agent.usd_ops import set_material, set_physics, create_joint


def make_stage(path: Path):
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 0.001)
    root = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(root.GetPrim())
    UsdGeom.Xform.Define(stage, "/World/A")
    UsdGeom.Cube.Define(stage, "/World/A/mesh").CreateSizeAttr(10)
    body = UsdGeom.Xform.Define(stage, "/World/B")
    body.AddTranslateOp().Set((100, 0, 0))
    UsdGeom.Cube.Define(stage, "/World/B/mesh").CreateSizeAttr(10)
    stage.GetRootLayer().Save()
    return stage


def test_transaction_revision_save_and_failure(tmp_path):
    path = tmp_path / "scene.usda"
    stage = make_stage(path)
    original = path.read_bytes()
    session = SceneSession(stage, tmp_path / "project")
    revision = session.revision
    spec = MaterialSpec(prim_paths=["/World/A"], color=(0.2, 0.3, 0.4))
    session.edit(revision, lambda current: set_material(current, spec))
    assert session.revision != revision
    with pytest.raises(ValueError, match="revision"):
        session.edit(revision, lambda current: set_material(current, spec))
    before = session.stage.Flatten().ExportToString()
    invalid = MaterialSpec(prim_paths=["/World/A", "/Missing"], color=(1, 0, 0))
    with pytest.raises(ValueError):
        session.edit(session.revision, lambda current: set_material(current, invalid))
    assert session.stage.Flatten().ExportToString() == before
    saved = session.save()
    reopened = Usd.Stage.Open(saved["path"])
    assert reopened.GetPrimAtPath("/World/A").HasRelationship("material:binding")
    assert path.read_bytes() == original


def test_mass_units_and_rotated_joint_frame(tmp_path):
    from pxr import UsdPhysics

    stage = make_stage(tmp_path / "scene.usda")
    UsdGeom.Xformable(stage.GetPrimAtPath("/World/B")).AddRotateZOp().Set(90)
    set_physics(stage, PhysicsSpec(prim_path="/World/A", mass_kg=2))
    set_physics(stage, PhysicsSpec(prim_path="/World/B", mass_kg=3))
    assert UsdPhysics.MassAPI(stage.GetPrimAtPath("/World/B")).GetMassAttr().Get() == 3
    assert any(prim.IsA(UsdPhysics.Scene) for prim in stage.Traverse())
    spec = JointSpec(path="/World/J", body0="/World/A", body1="/World/B",
                     anchor_m=(0.1, 0, 0), axis=(0, 0, 1), limits=(-1, 1))
    create_joint(stage, spec)
    joint = UsdPhysics.RevoluteJoint(stage.GetPrimAtPath("/World/J"))
    assert Gf.IsClose(joint.GetLocalPos0Attr().Get(), Gf.Vec3f(100, 0, 0), 1e-4)
    assert Gf.IsClose(joint.GetLocalPos1Attr().Get(), Gf.Vec3f(0, 0, 0), 1e-4)
    assert joint.GetUpperLimitAttr().Get() == pytest.approx(57.2957795)
    drive = UsdPhysics.DriveAPI(joint, "angular")
    assert drive.GetStiffnessAttr().Get() == pytest.approx(1000 * 1e6 * 3.141592653589793 / 180)
    assert drive.GetMaxForceAttr().Get() == pytest.approx(10000 * 1e6)


def test_manual_edit_invalidates_revision(tmp_path):
    session = SceneSession(make_stage(tmp_path / "scene.usda"), tmp_path / "project")
    revision = session.revision
    session.stage.GetPrimAtPath("/World/A").SetDisplayName("夹具")
    assert revision != session.revision


def test_reopen_project_preserves_existing_edits(tmp_path):
    path = tmp_path / "source.usda"
    session = SceneSession(make_stage(path), tmp_path / "project")
    session.edit(session.revision, lambda stage: set_material(stage, MaterialSpec(prim_paths=["/World/A"])))
    first = session.save()
    files = {item: item.read_bytes() for item in (tmp_path / "project").glob("*.usda")}
    reopened = SceneSession(Usd.Stage.Open(first["path"]), tmp_path / "project")
    second = reopened.save()
    for item, content in files.items():
        assert item.read_bytes() == content
    assert Usd.Stage.Open(second["path"]).GetPrimAtPath("/World/A").HasRelationship("material:binding")


async def test_texture_copied_and_saved_with_relative_reference(tmp_path):
    from pxr import UsdShade
    from workcell_agent.dispatch import Dispatcher
    from workcell_agent.models import OperationRequest

    texture = tmp_path / "纹理 image.ppm"
    texture.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    session = SceneSession(make_stage(tmp_path / "source.usda"), tmp_path / "project")
    result = await Dispatcher(session).execute(OperationRequest(
        operation="set_material", scene_revision=session.revision,
        parameters={"prim_paths": ["/World/A"], "texture": str(texture)}))
    texture.unlink()
    saved = session.save()
    reopened = Usd.Stage.Open(saved["path"])
    asset = UsdShade.Shader(reopened.GetPrimAtPath(result["material"] + "/Texture")).GetInput("file").Get()
    assert not Path(asset.path).is_absolute()
    assert Path(asset.resolvedPath).read_bytes() == b"P6\n1 1\n255\n\xff\x00\x00"
    assert UsdGeom.GetStageMetersPerUnit(reopened) == 0.001


def test_restart_session_saves_existing_edits_and_dirty_source(tmp_path):
    path = tmp_path / "source.usda"
    stage = make_stage(path)
    original = path.read_bytes()
    first = SceneSession(stage, tmp_path / "project")
    first.edit(first.revision, lambda current: UsdGeom.Cube.Define(current, "/World/Added"))
    first.close()
    UsdGeom.Cube.Define(stage, "/World/RootEdit")
    second = SceneSession(stage, tmp_path / "project")
    saved = Usd.Stage.Open(second.save()["path"])
    assert saved.GetPrimAtPath("/World/Added")
    assert saved.GetPrimAtPath("/World/RootEdit")
    assert path.read_bytes() == original


def test_dirty_source_sublayer_preserved_in_separate_process(tmp_path):
    import subprocess
    import sys
    from pxr import Sdf

    child = make_stage(tmp_path / "child.usda")
    original = (tmp_path / "child.usda").read_bytes()
    layer = Sdf.Layer.CreateNew(str(tmp_path / "root.usda"))
    layer.subLayerPaths = ["child.usda"]
    layer.Save()
    stage = Usd.Stage.Open(layer)
    UsdGeom.Cube.Define(child, "/UnsavedChild")
    session = SceneSession(stage, tmp_path / "project")
    saved = session.save()
    result = subprocess.check_output([sys.executable, "-c",
        "import sys; from pxr import Usd; s=Usd.Stage.Open(sys.argv[1]); print(bool(s.GetPrimAtPath('/UnsavedChild')))",
        saved["path"]], text=True)
    assert result.strip() == "True"
    assert (tmp_path / "child.usda").read_bytes() == original
