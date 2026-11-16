import pytest
from pxr import Gf, Usd, UsdGeom, UsdShade

from workcell_agent.models import MaterialSpec
from workcell_agent.usd_ops import set_material


def make_mesh(stage):
    mesh = UsdGeom.Mesh.Define(stage, "/World/Part/Geometry")
    mesh.CreatePointsAttr([(0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)])
    mesh.CreateFaceVertexCountsAttr([4])
    mesh.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    return mesh


def test_texture_creates_face_varying_uvs(tmp_path):
    stage = Usd.Stage.CreateInMemory()
    mesh = make_mesh(stage)
    texture = tmp_path / "color.ppm"
    texture.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    result = set_material(stage, MaterialSpec(prim_paths=["/World/Part"], texture=str(texture)))
    uv = UsdGeom.PrimvarsAPI(mesh).GetPrimvar("st")
    assert uv and uv.GetInterpolation() == "faceVarying"
    assert list(uv.ComputeFlattened()) == [Gf.Vec2f(0, 0), Gf.Vec2f(1, 0), Gf.Vec2f(1, 1), Gf.Vec2f(0, 1)]
    shader = UsdShade.Shader(stage.GetPrimAtPath(result["material"] + "/Texture"))
    assert shader.GetInput("sourceColorSpace").Get() == "sRGB"


def test_existing_uv_mode_rejects_missing_coordinates(tmp_path):
    stage = Usd.Stage.CreateInMemory()
    make_mesh(stage)
    texture = tmp_path / "color.ppm"
    texture.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
    with pytest.raises(ValueError, match="UV"):
        set_material(stage, MaterialSpec(prim_paths=["/World/Part"], texture=str(texture), uv_projection="existing"))
