import math

import pytest
from pxr import Gf, Usd, UsdGeom, UsdShade, UsdPhysics

from workcell_agent.models import AutoMaterialSpec, VideoSpec
from workcell_agent.presentation import auto_material, create_presentation
from workcell_agent.scene import SceneSession
from test_materials import make_mesh


def test_auto_material_authors_visual_parameters():
    stage = Usd.Stage.CreateInMemory()
    mesh = make_mesh(stage)
    physics = UsdPhysics.MassAPI.Apply(mesh.GetPrim())
    physics.CreateMassAttr(12)
    result = auto_material(stage, AutoMaterialSpec(prim_paths=["/World/Part"], color=(0.1, 0.2, 0.3),
                                                  metallic=0.6, roughness=0.2, opacity=0.8))
    material, _ = UsdShade.MaterialBindingAPI(mesh).ComputeBoundMaterial()
    assert str(material.GetPath()) == result["material"]
    shader = UsdShade.Shader(material.GetSurfaceOutput().GetConnectedSource()[0].GetPrim())
    assert shader.GetInput("diffuseColor").Get() == Gf.Vec3f(0.1, 0.2, 0.3)
    assert shader.GetInput("metallic").Get() == pytest.approx(0.6)
    assert shader.GetInput("roughness").Get() == pytest.approx(0.2)
    assert shader.GetInput("opacity").Get() == pytest.approx(0.8)
    assert physics.GetMassAttr().Get() == 12


@pytest.mark.parametrize("up_axis", ["Y", "Z"])
def test_orbit_contains_entire_model(up_axis):
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.SetStageUpAxis(stage, up_axis)
    cube = UsdGeom.Cube.Define(stage, "/World/Part")
    cube.AddTranslateOp().Set((100, -20, 4))
    cube.AddScaleOp().Set((3, 1, 7))
    stage.SetTimeCodesPerSecond(24)
    spec = VideoSpec(prim_path="/World/Part", duration_s=1, fps=12, width=640, height=480)
    result = create_presentation(stage, spec)
    camera = UsdGeom.Camera(stage.GetPrimAtPath(result["camera"]))
    assert result["frame_count"] == 12
    assert len(UsdGeom.Xformable(camera).GetOrderedXformOps()[0].GetTimeSamples()) == 12
    bounds = UsdGeom.BBoxCache(0, ["default", "render"]).ComputeWorldBound(cube.GetPrim()).ComputeAlignedRange()
    for frame in range(12):
        time = frame * 24 / 12
        gf_camera = camera.GetCamera(time)
        matrix = gf_camera.frustum.ComputeViewMatrix() * gf_camera.frustum.ComputeProjectionMatrix()
        for corner in range(8):
            point = matrix.Transform(bounds.GetCorner(corner))
            assert all(math.isfinite(value) for value in point)
            assert abs(point[0]) < 1 and abs(point[1]) < 1
            assert -1 <= point[2] <= 1
    assert camera.GetCamera(0).transform.Transform(Gf.Vec3d(0)) != camera.GetCamera(2).transform.Transform(Gf.Vec3d(0))


def test_presentation_rejects_empty_asset():
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Xform.Define(stage, "/World/Empty")
    with pytest.raises(ValueError, match="包围盒"):
        create_presentation(stage, VideoSpec(prim_path="/World/Empty"))


def test_video_rejects_odd_resolution():
    with pytest.raises(ValueError):
        VideoSpec(prim_path="/World/Part", width=641)


def test_presentation_cleanup_preserves_asset(tmp_path):
    stage = Usd.Stage.CreateInMemory()
    UsdGeom.Cube.Define(stage, "/World/Part")
    session = SceneSession(stage, tmp_path)
    try:
        for _ in range(2):
            result = session.edit(session.revision, lambda current: create_presentation(
                current, VideoSpec(prim_path="/World/Part", duration_s=1, fps=1)))
            assert stage.GetPrimAtPath(result["camera"])
            with Usd.EditContext(stage, session.layer):
                stage.RemovePrim(result["presentation_root"])
            assert not stage.GetPrimAtPath(result["presentation_root"])
        assert [str(prim.GetPath()) for prim in stage.Traverse()] == ["/World", "/World/Part"]
    finally:
        session.close()
