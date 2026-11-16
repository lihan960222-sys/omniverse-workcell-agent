import math
from pathlib import Path
from uuid import uuid4

from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdPhysics

from .models import MaterialSpec, PhysicsSpec, JointSpec


def require_prim(stage, path):
    sdf_path = Sdf.Path(path)
    if not sdf_path.IsAbsolutePath() or not sdf_path.IsPrimPath():
        raise ValueError(f"对象路径必须是绝对 Prim 路径: {path}")
    prim = stage.GetPrimAtPath(sdf_path)
    if not prim or prim.IsInstanceProxy():
        raise ValueError(f"对象不存在或属于不可直接修改的实例: {path}")
    return prim


def set_material(stage: Usd.Stage, spec: MaterialSpec):
    prims = [require_prim(stage, path) for path in spec.prim_paths]
    if spec.texture and not Path(spec.texture).is_file():
        raise ValueError(f"纹理文件不存在: {spec.texture}")
    path = "/WorkcellMaterials/m_" + uuid4().hex
    material = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, path + "/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    for name, value in (("metallic", spec.metallic), ("roughness", spec.roughness), ("opacity", spec.opacity)):
        shader.CreateInput(name, Sdf.ValueTypeNames.Float).Set(value)
    color = shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f)
    color.Set(Gf.Vec3f(*spec.color))
    if spec.texture:
        texture = UsdShade.Shader.Define(stage, path + "/Texture")
        texture.CreateIdAttr("UsdUVTexture")
        texture.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(Sdf.AssetPath(Path(spec.texture).resolve().as_posix()))
        reader = UsdShade.Shader.Define(stage, path + "/UV")
        reader.CreateIdAttr("UsdPrimvarReader_float2")
        reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
        texture.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(reader.ConnectableAPI(), "result")
        color.ConnectToSource(texture.ConnectableAPI(), "rgb")
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    for prim in prims:
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)
    return {"modified": spec.prim_paths, "material": path}


def set_physics(stage: Usd.Stage, spec: PhysicsSpec):
    prim = require_prim(stage, spec.prim_path)
    if not prim.IsA(UsdGeom.Xformable):
        raise ValueError("刚体对象需要支持坐标变换")
    if prim.IsInstance():
        prim.SetInstanceable(False)
    for child in Usd.PrimRange(prim):
        if child != prim and (child.HasAPI(UsdPhysics.RigidBodyAPI) or child.IsInstance()):
            raise ValueError("请选择单个部件，当前对象包含其他刚体或嵌套实例")
    ancestor = prim.GetParent()
    while ancestor and not ancestor.IsPseudoRoot():
        if ancestor.HasAPI(UsdPhysics.RigidBodyAPI):
            raise ValueError("部件的父级已经配置刚体")
        ancestor = ancestor.GetParent()
    meters = UsdGeom.GetStageMetersPerUnit(stage)
    kilograms = UsdPhysics.GetStageKilogramsPerUnit(stage)
    body = UsdPhysics.RigidBodyAPI.Apply(prim)
    body.CreateRigidBodyEnabledAttr(True)
    body.CreateKinematicEnabledAttr(spec.kinematic)
    mass = UsdPhysics.MassAPI.Apply(prim)
    mass.CreateMassAttr(spec.mass_kg / kilograms)
    if spec.diagonal_inertia:
        mass.CreateDiagonalInertiaAttr(Gf.Vec3f(*(value / (kilograms * meters * meters)
                                               for value in spec.diagonal_inertia)))
    material = UsdShade.Material.Define(stage, "/WorkcellMaterials/p_" + uuid4().hex)
    physics = UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics.CreateStaticFrictionAttr(spec.static_friction)
    physics.CreateDynamicFrictionAttr(spec.dynamic_friction)
    physics.CreateRestitutionAttr(spec.restitution)
    colliders = []
    for child in Usd.PrimRange(prim):
        if child.IsA(UsdGeom.Gprim):
            UsdPhysics.CollisionAPI.Apply(child).CreateCollisionEnabledAttr(True)
            if child.IsA(UsdGeom.Mesh):
                UsdPhysics.MeshCollisionAPI.Apply(child).CreateApproximationAttr(spec.collision)
            UsdShade.MaterialBindingAPI.Apply(child).Bind(material, materialPurpose="physics")
            colliders.append(str(child.GetPath()))
    if not colliders:
        raise ValueError("刚体下面没有可以配置碰撞的几何对象")
    if not any(item.IsA(UsdPhysics.Scene) for item in stage.Traverse()):
        scene = UsdPhysics.Scene.Define(stage, "/WorkcellPhysicsScene")
        up_axis = UsdGeom.GetStageUpAxis(stage)
        direction = Gf.Vec3f(0, 0, -1) if up_axis == "Z" else Gf.Vec3f(0, -1, 0)
        scene.CreateGravityDirectionAttr(direction)
        scene.CreateGravityMagnitudeAttr(9.81 / meters)
    return {"modified": [spec.prim_path], "colliders": colliders}


def create_joint(stage: Usd.Stage, spec: JointSpec):
    body1 = require_prim(stage, spec.body1)
    body0 = require_prim(stage, spec.body0) if spec.body0 else None
    root = require_prim(stage, spec.articulation_root) if spec.articulation_root else None
    for prim in (body0, body1):
        if prim and not prim.HasAPI(UsdPhysics.RigidBodyAPI):
            raise ValueError(f"关节对象需要先配置刚体: {prim.GetPath()}")
    if stage.GetPrimAtPath(spec.path):
        raise ValueError(f"关节路径已经存在: {spec.path}")
    meters = UsdGeom.GetStageMetersPerUnit(stage)
    axis = Gf.Vec3d(*spec.axis).GetNormalized()
    frame = Gf.Matrix4d(1)
    frame.SetRotate(Gf.Rotation(Gf.Vec3d(1, 0, 0), axis))
    frame.SetTranslateOnly(Gf.Vec3d(*(value / meters for value in spec.anchor_m)))
    cache = UsdGeom.XformCache()
    frames = []
    for prim in (body0, body1):
        matrix = cache.GetLocalToWorldTransform(prim) if prim else Gf.Matrix4d(1)
        scale = Gf.Transform(matrix).GetScale()
        if not Gf.IsClose(scale, Gf.Vec3d(1), 1e-6):
            raise ValueError("关节部件包含缩放，请在创建机构前处理几何缩放")
        frames.append(frame * matrix.GetInverse())
    schema = {"fixed": UsdPhysics.FixedJoint, "revolute": UsdPhysics.RevoluteJoint,
              "prismatic": UsdPhysics.PrismaticJoint}[spec.kind]
    joint = schema.Define(stage, spec.path)
    if body0:
        joint.CreateBody0Rel().SetTargets([body0.GetPath()])
    joint.CreateBody1Rel().SetTargets([body1.GetPath()])
    if root:
        UsdPhysics.ArticulationRootAPI.Apply(root)
    for index, local in enumerate(frames):
        getattr(joint, f"CreateLocalPos{index}Attr")(Gf.Vec3f(local.ExtractTranslation()))
        quat = local.ExtractRotationQuat()
        getattr(joint, f"CreateLocalRot{index}Attr")(Gf.Quatf(quat.GetReal(), Gf.Vec3f(quat.GetImaginary())))
    if spec.kind != "fixed":
        joint.CreateAxisAttr("X")
        factor = 180 / math.pi if spec.kind == "revolute" else 1 / meters
        joint.CreateLowerLimitAttr(spec.limits[0] * factor)
        joint.CreateUpperLimitAttr(spec.limits[1] * factor)
        drive = UsdPhysics.DriveAPI.Apply(joint.GetPrim(), "angular" if spec.kind == "revolute" else "linear")
        drive.CreateTypeAttr("force")
        kilograms = UsdPhysics.GetStageKilogramsPerUnit(stage)
        force_factor = 1 / (kilograms * meters ** (2 if spec.kind == "revolute" else 1))
        gain_factor = force_factor / factor
        drive.CreateStiffnessAttr(spec.stiffness * gain_factor)
        drive.CreateDampingAttr(spec.damping * gain_factor)
        drive.CreateMaxForceAttr(spec.max_force * force_factor)
    return {"joint": spec.path}
