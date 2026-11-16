from pathlib import Path

from pxr import Gf, Usd, UsdGeom, UsdPhysics, UsdLux

from .models import PhysicsSpec, JointSpec, MaterialSpec
from .usd_ops import set_physics, create_joint, set_material


def create_example(path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = Usd.Stage.CreateNew(str(path))
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())
    UsdGeom.Xform.Define(stage, "/World/Mechanism")
    physics = UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    physics.CreateGravityDirectionAttr(Gf.Vec3f(0, 0, -1))
    physics.CreateGravityMagnitudeAttr(9.81)
    UsdLux.DomeLight.Define(stage, "/World/Light").CreateIntensityAttr(500)
    for name, z, dimensions in (("Base", 0.05, (0.4, 0.2, 0.1)),
                                ("Slider", 0.13, (0.08, 0.08, 0.06)),
                                ("Clamp", 0.19, (0.1, 0.03, 0.04))):
        body = UsdGeom.Xform.Define(stage, f"/World/Mechanism/{name}")
        body.AddTranslateOp().Set((0, 0, z))
        mesh = UsdGeom.Cube.Define(stage, f"/World/Mechanism/{name}/Mesh")
        mesh.CreateSizeAttr(1)
        mesh.AddScaleOp().Set(dimensions)
        set_physics(stage, PhysicsSpec(prim_path=str(body.GetPath()), mass_kg=1))
    create_joint(stage, JointSpec(path="/World/Mechanism/BaseFixed", body1="/World/Mechanism/Base",
                                 kind="fixed", anchor_m=(0, 0, 0.05),
                                 articulation_root="/World/Mechanism"))
    create_joint(stage, JointSpec(path="/World/Mechanism/Slide", body0="/World/Mechanism/Base",
                                 body1="/World/Mechanism/Slider", kind="prismatic", anchor_m=(0, 0, 0.13),
                                 axis=(1, 0, 0), limits=(0, 0.4), stiffness=10000, damping=1000))
    create_joint(stage, JointSpec(path="/World/Mechanism/Rotate", body0="/World/Mechanism/Slider",
                                 body1="/World/Mechanism/Clamp", anchor_m=(0, 0, 0.19), axis=(0, 0, 1),
                                 limits=(-1.57, 1.57)))
    obstacle = UsdGeom.Cube.Define(stage, "/World/Obstacle")
    obstacle.CreateSizeAttr(0.08)
    obstacle.AddTranslateOp().Set((0.25, 0, 0.13))
    UsdPhysics.CollisionAPI.Apply(obstacle.GetPrim())
    set_material(stage, MaterialSpec(prim_paths=["/World/Mechanism/Slider"], color=(0.1, 0.5, 0.8)))
    stage.GetRootLayer().Save()
    return path.resolve()
