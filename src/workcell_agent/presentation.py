import math
from uuid import uuid4

from pxr import Gf, Usd, UsdGeom, UsdLux

from .models import AutoMaterialSpec, MaterialSpec, VideoSpec
from .usd_ops import require_prim, set_material


def auto_material(stage, spec: AutoMaterialSpec):
    result = set_material(stage, MaterialSpec(**spec.model_dump()))
    return {**result, "visual_parameters": spec.model_dump(exclude={"prim_paths"})}


def create_presentation(stage, spec: VideoSpec):
    prim = require_prim(stage, spec.prim_path)
    bounds = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"]).ComputeWorldBound(prim).ComputeAlignedRange()
    if bounds.IsEmpty():
        raise ValueError("模型没有可显示的包围盒")
    center = bounds.GetMidpoint()
    radius = bounds.GetSize().GetLength() / 2
    if not math.isfinite(radius) or radius <= 0 or not all(math.isfinite(value) for value in center):
        raise ValueError("模型包围盒无效")
    root = f"/WorkcellPresentation_{uuid4().hex}"
    UsdGeom.Xform.Define(stage, root)
    camera = UsdGeom.Camera.Define(stage, root + "/Camera")
    camera.CreateFocalLengthAttr(35)
    camera.CreateHorizontalApertureAttr(36)
    camera.CreateVerticalApertureAttr(36 * spec.height / spec.width)
    half_angle = math.atan(min(36, 36 * spec.height / spec.width) / 70)
    distance = radius / math.sin(half_angle) * 1.15
    camera.CreateClippingRangeAttr(Gf.Vec2f(max(radius * 0.001, 1e-6), distance + radius * 3))
    transform = camera.AddTransformOp()
    frame_count = round(spec.duration_s * spec.fps)
    tps = stage.GetTimeCodesPerSecond()
    up_z = UsdGeom.GetStageUpAxis(stage) == "Z"
    up = Gf.Vec3d(0, 0, 1) if up_z else Gf.Vec3d(0, 1, 0)
    for frame in range(frame_count):
        angle = 2 * math.pi * frame / frame_count
        horizontal = math.sqrt(1 - 0.35 ** 2)
        x, y, z = distance * horizontal * math.cos(angle), distance * horizontal * math.sin(angle), distance * 0.35
        eye = center + (Gf.Vec3d(x, y, z) if up_z else Gf.Vec3d(x, z, y))
        matrix = Gf.Matrix4d().SetLookAt(eye, center, up).GetInverse()
        transform.Set(matrix, frame * tps / spec.fps)
        if frame == 0:
            transform.Set(matrix)
    dome = UsdLux.DomeLight.Define(stage, root + "/Fill")
    dome.CreateIntensityAttr(700)
    key = UsdLux.DistantLight.Define(stage, root + "/Key")
    key.CreateIntensityAttr(2500)
    key.CreateAngleAttr(15)
    key.AddRotateXYZOp().Set((-35, -45, 0))
    return {"camera": str(camera.GetPath()), "presentation_root": root, "frame_count": frame_count,
            "duration_s": frame_count / spec.fps, "fps": spec.fps, "width": spec.width, "height": spec.height}
