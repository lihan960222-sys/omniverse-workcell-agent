import hashlib
import itertools
import math
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Builder, BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.Precision import Precision
from OCP.ShapeAnalysis import ShapeAnalysis_ShapeTolerance
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence, TDF_Tool
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.gp import gp_Trsf
from pydantic import BaseModel, ConfigDict, Field
from pxr import Gf, Sdf, Tf, Usd, UsdGeom, Vt


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    brep_file: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Part(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prim_path: str
    definition_id: str
    name: str


class GeometryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    source_name: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage_file: str
    mesh_file: str
    mesh_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    length_unit: Literal["m"] = "m"
    brep_length_unit: Literal["mm"] = "mm"
    tessellation_tolerance_m: float = Field(gt=0, allow_inf_nan=False)
    angular_tolerance_rad: float = Field(gt=0, allow_inf_nan=False)
    definitions: dict[str, Definition]
    parts: list[Part]


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _asset_path(directory: Path, relative: str) -> Path:
    path = (directory / relative).resolve(strict=True)
    if not path.is_relative_to(directory.resolve()):
        raise ValueError(f"几何文件必须位于工程目录内：{relative}")
    return path


def _entry(label: TDF_Label) -> str:
    value = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, value)
    return value.ToCString()


def _name(label: TDF_Label) -> str:
    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return attribute.Get().ToExtString()
    return "Part"


def _matrix(location: TopLoc_Location) -> Gf.Matrix4d:
    transform = location.Transformation()
    return Gf.Matrix4d(
        transform.Value(1, 1), transform.Value(2, 1), transform.Value(3, 1), 0,
        transform.Value(1, 2), transform.Value(2, 2), transform.Value(3, 2), 0,
        transform.Value(1, 3), transform.Value(2, 3), transform.Value(3, 3), 0,
        transform.Value(1, 4) * 0.001, transform.Value(2, 4) * 0.001, transform.Value(3, 4) * 0.001, 1,
    )


def _write_mesh(shape: TopoDS_Shape, stage: Usd.Stage, path: str, tolerance: float) -> None:
    mesher = BRepMesh_IncrementalMesh(shape, tolerance * 1000.0, False, 0.2, True)
    if not mesher.IsDone():
        raise ValueError(f"BRep 三角化失败：{path}")
    points = []
    indices = []
    faces = TopExp_Explorer(shape, TopAbs_FACE)
    while faces.More():
        face = TopoDS.Face_s(faces.Current())
        location = TopLoc_Location()
        triangulation = BRep_Tool.Triangulation_s(face, location)
        if triangulation is None or triangulation.NbTriangles() == 0:
            raise ValueError(f"BRep 面缺少三角形：{path}")
        offset = len(points)
        transform = location.Transformation()
        for index in range(1, triangulation.NbNodes() + 1):
            point = triangulation.Node(index).Transformed(transform)
            points.append(Gf.Vec3f(point.X() * 0.001, point.Y() * 0.001, point.Z() * 0.001))
        for index in range(1, triangulation.NbTriangles() + 1):
            triangle = triangulation.Triangle(index)
            order = (1, 3, 2) if face.Orientation() == TopAbs_REVERSED else (1, 2, 3)
            indices.extend(offset + triangle.Value(vertex) - 1 for vertex in order)
        faces.Next()
    if not points:
        raise ValueError(f"几何不包含可显示的面：{path}")
    mesh = UsdGeom.Mesh.Define(stage, path)
    mesh.CreatePointsAttr(Vt.Vec3fArray(points))
    mesh.CreateFaceVertexIndicesAttr(indices)
    mesh.CreateFaceVertexCountsAttr([3] * (len(indices) // 3))
    mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
    mesh.CreateExtentAttr(UsdGeom.PointBased.ComputeExtent(Vt.Vec3fArray(points)))


def convert_step(source: Path, output_directory: Path) -> dict:
    source = Path(source).resolve(strict=True)
    if source.suffix.lower() not in {".stp", ".step"}:
        raise ValueError("输入文件必须是 .stp 或 .step")
    output_directory = Path(output_directory).resolve()
    if output_directory.exists():
        raise FileExistsError(f"输出目录已经存在：{output_directory}")
    Interface_Static.SetCVal_s("xstep.cascade.unit", "MM")
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if reader.ReadFile(str(source)) != IFSelect_RetDone:
        raise ValueError(f"STEP 读取失败：{source}")
    # OCCT 使用毫米建模，避免其默认绝对容差吞并微小装配间隙。
    reader.ChangeReader().SetSystemLengthUnit(1.0)
    document = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    if not reader.Transfer(document):
        raise ValueError(f"STEP 装配转换失败：{source}")
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    if roots.Length() == 0:
        raise ValueError("STEP 不包含可转换的装配部件")
    output_directory.mkdir(parents=True)
    geometry_directory = output_directory / "geometry"
    geometry_directory.mkdir()
    stage_path = output_directory / "workcell.usda"
    mesh_path = output_directory / "geometry.usdc"
    stage = Usd.Stage.CreateNew(str(stage_path))
    meshes = Usd.Stage.CreateNew(str(mesh_path))
    for target in (stage, meshes):
        UsdGeom.SetStageMetersPerUnit(target, 1.0)
        UsdGeom.SetStageUpAxis(target, UsdGeom.Tokens.z)
    root = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(root.GetPrim())
    definitions = {}
    parts = []
    tolerance = 0.0001

    def visit(label: TDF_Label, parent: str, ancestors: frozenset[str]) -> None:
        reference = TDF_Label()
        is_reference = shape_tool.IsReference_s(label)
        if is_reference:
            if not shape_tool.GetReferredShape_s(label, reference):
                raise ValueError(f"装配引用无法读取：{_entry(label)}")
        else:
            reference = label
        definition_id = "part_" + _entry(reference).replace(":", "_")
        if definition_id in ancestors:
            raise ValueError(f"装配包含循环引用：{_entry(label)}")
        name = _name(label)
        identifier = Tf.MakeValidIdentifier(name) + "_" + _entry(label).replace(":", "_")
        prim_path = parent + "/" + identifier
        prim = UsdGeom.Xform.Define(stage, prim_path)
        location = shape_tool.GetLocation_s(label) if is_reference else TopLoc_Location()
        prim.AddTransformOp().Set(_matrix(location))
        prim.GetPrim().SetDisplayName(name)
        if shape_tool.IsAssembly_s(reference):
            children = TDF_LabelSequence()
            shape_tool.GetComponents_s(reference, children)
            for child in children:
                visit(child, prim_path, ancestors | {definition_id})
            return
        if definition_id not in definitions:
            shape = shape_tool.GetShape_s(reference)
            if shape.IsNull() or not BRepCheck_Analyzer(shape).IsValid():
                raise ValueError(f"部件 BRep 无效：{name}")
            brep_path = geometry_directory / f"{definition_id}.brep"
            if not BRepTools.Write_s(shape, str(brep_path)):
                raise OSError(f"BRep 文件写入失败：{brep_path}")
            _write_mesh(shape, meshes, f"/{definition_id}/Geometry", tolerance)
            definitions[definition_id] = Definition(
                brep_file=brep_path.relative_to(output_directory).as_posix(), sha256=_digest(brep_path)
            )
        prim.GetPrim().GetReferences().AddReference(mesh_path.name, f"/{definition_id}")
        prim.GetPrim().SetInstanceable(True)
        prim.GetPrim().SetCustomDataByKey("workcell:definitionId", definition_id)
        parts.append(Part(prim_path=prim_path, definition_id=definition_id, name=name))

    for label in roots:
        visit(label, "/World", frozenset())
    if not parts:
        raise ValueError("STEP 装配不包含可转换的叶节点部件")
    meshes.GetRootLayer().Save()
    stage.GetRootLayer().Save()
    manifest = GeometryManifest(
        source_name=source.name, source_sha256=_digest(source), stage_file=stage_path.name,
        mesh_file=mesh_path.name, mesh_sha256=_digest(mesh_path), tessellation_tolerance_m=tolerance,
        angular_tolerance_rad=0.2, definitions=definitions, parts=parts,
    )
    manifest_path = output_directory / "geometry.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return {"usd_path": str(stage_path), "geometry_manifest": str(manifest_path), "part_count": len(parts)}


def _load(manifest_path: Path, stage_path: Path | None, asset_root: str):
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest = GeometryManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    target = Sdf.Path(asset_root)
    if not target.IsAbsolutePath() or not target.IsPrimPath():
        raise ValueError("asset_root 必须是绝对 Prim 路径")
    manifest.parts = [part.model_copy(update={"prim_path": str(
        Sdf.Path(part.prim_path).ReplacePrefix(Sdf.Path("/World"), target))}) for part in manifest.parts]
    directory = manifest_path.parent
    mesh_file = _asset_path(directory, manifest.mesh_file)
    if _digest(mesh_file) != manifest.mesh_sha256:
        raise ValueError("USD Mesh 的 SHA-256 已改变，需要重新转换并建立几何映射")
    shapes = {}
    for identifier, definition in manifest.definitions.items():
        brep_file = _asset_path(directory, definition.brep_file)
        if _digest(brep_file) != definition.sha256:
            raise ValueError(f"BRep 的 SHA-256 已改变：{identifier}")
        shape = TopoDS_Shape()
        if not BRepTools.Read_s(shape, str(brep_file), BRep_Builder()):
            raise ValueError(f"BRep 文件读取失败：{brep_file}")
        if shape.IsNull() or not BRepCheck_Analyzer(shape).IsValid():
            raise ValueError(f"BRep 无效：{identifier}")
        shapes[identifier] = shape
    current_stage = Path(stage_path).resolve(strict=True) if stage_path else _asset_path(directory, manifest.stage_file)
    stage = Usd.Stage.Open(str(current_stage))
    paths = [part.prim_path for part in manifest.parts]
    if len(set(paths)) != len(paths) or not paths:
        raise ValueError("几何映射需要互不重复的部件路径")
    original_meshes = Usd.Stage.Open(str(mesh_file))
    for part in manifest.parts:
        if part.definition_id not in shapes:
            raise ValueError(f"部件引用的 BRep 不存在：{part.prim_path}")
        original = original_meshes.GetPrimAtPath(f"/{part.definition_id}/Geometry")
        current = stage.GetPrimAtPath(part.prim_path + "/Geometry")
        if not original or not current or not current.IsA(UsdGeom.Mesh):
            raise ValueError(f"USD 场景中缺少映射的 Mesh：{part.prim_path}")
        for name in ("points", "faceVertexIndices", "faceVertexCounts", "orientation", "subdivisionScheme"):
            attribute = current.GetAttribute(name)
            if attribute.GetNumTimeSamples() or attribute.Get() != original.GetAttribute(name).Get():
                raise ValueError(f"USD Mesh 的 {name} 已改变，需要重新建立几何映射：{part.prim_path}")
    return manifest, stage, shapes


def _world_shape(part: Part, shape: TopoDS_Shape, stage: Usd.Stage) -> TopoDS_Shape:
    prim = stage.GetPrimAtPath(part.prim_path)
    if not prim or not prim.IsActive():
        raise ValueError(f"USD 场景中找不到部件：{part.prim_path}")
    mesh = stage.GetPrimAtPath(part.prim_path + "/Geometry")
    if not mesh or not mesh.IsA(UsdGeom.Mesh):
        raise ValueError(f"USD 场景中缺少映射的 Mesh：{part.prim_path}")
    # 叶节点 Mesh 的局部编辑会使其与保存的 BRep 不一致。
    if UsdGeom.Xformable(mesh).GetOrderedXformOps():
        raise ValueError(f"请在部件 Xform 上调整位置：{mesh.GetPath()}")
    matrix = UsdGeom.XformCache().GetLocalToWorldTransform(prim)
    scale = UsdGeom.GetStageMetersPerUnit(stage)
    values = [matrix[row][col] for row in range(4) for col in range(4)]
    if not all(math.isfinite(value) for value in values) or not math.isfinite(scale) or scale <= 0:
        raise ValueError("USD 变换或单位包含无效数值")
    axes = [Gf.Vec3d(matrix[index][0], matrix[index][1], matrix[index][2]) for index in range(3)]
    lengths = [axis.GetLength() for axis in axes]
    if (min(lengths) <= 1e-12 or max(lengths) - min(lengths) > max(lengths) * 1e-8
            or any(abs(Gf.Dot(axes[a], axes[b])) > lengths[a] * lengths[b] * 1e-8
                   for a, b in ((0, 1), (0, 2), (1, 2))) or matrix.GetDeterminant() <= 0):
        raise ValueError(f"几何检查要求正向均匀缩放和正交坐标：{part.prim_path}")
    transform = gp_Trsf()
    transform.SetValues(*(matrix[col][row] * scale * (1000.0 if col == 3 else 1.0)
                          for row in range(3) for col in range(4)))
    operation = BRepBuilderAPI_Transform(shape, transform, True)
    if not operation.IsDone():
        raise ValueError(f"部件世界坐标转换失败：{part.prim_path}")
    return operation.Shape()


def _coordinates(point, scale: float = 0.001) -> list[float]:
    return [point.X() * scale, point.Y() * scale, point.Z() * scale]


def check_interference(
    manifest: Path, length_tolerance_m: float = 1e-6, volume_tolerance_m3: float = 1e-12,
    stage_path: Path | None = None, asset_root: str = "/World",
) -> dict:
    if not math.isfinite(length_tolerance_m) or length_tolerance_m <= 0:
        raise ValueError("长度容差必须是有限正数")
    if not math.isfinite(volume_tolerance_m3) or volume_tolerance_m3 < 0:
        raise ValueError("体积容差必须是有限非负数")
    data, stage, definitions = _load(manifest, stage_path, asset_root)
    parts = []
    kernel_tolerance_m = Precision.Confusion_s() * 0.001
    for part in data.parts:
        shape = _world_shape(part, definitions[part.definition_id], stage)
        if not TopExp_Explorer(shape, TopAbs_SOLID).More() or TopExp_Explorer(shape, TopAbs_FACE, TopAbs_SOLID).More():
            raise ValueError(f"体积干涉检查要求封闭实体：{part.prim_path}")
        bounds = Bnd_Box()
        BRepBndLib.AddOptimal_s(shape, bounds, False, True)
        bounds.Enlarge(length_tolerance_m * 1000.0)
        kernel_tolerance_m = max(kernel_tolerance_m, ShapeAnalysis_ShapeTolerance().Tolerance(shape, 1) * 0.001)
        parts.append((part, shape, bounds))
    if length_tolerance_m < kernel_tolerance_m:
        raise ValueError(f"请求长度容差小于 BRep 的实际容差：{kernel_tolerance_m} m")
    findings = []
    narrow_phase_pairs = 0
    bbox_separated_pairs = 0
    for (first, shape_a, bounds_a), (second, shape_b, bounds_b) in itertools.combinations(parts, 2):
        if bounds_a.IsOut(bounds_b):
            bbox_separated_pairs += 1
            continue
        narrow_phase_pairs += 1
        common = BRepAlgoAPI_Common(shape_a, shape_b)
        if not common.IsDone() or common.Shape().IsNull():
            raise ValueError(f"共同实体计算失败：{first.prim_path}，{second.prim_path}")
        properties = GProp_GProps()
        BRepGProp.VolumeProperties_s(common.Shape(), properties, True)
        volume = abs(properties.Mass()) * 1e-9
        distance = BRepExtrema_DistShapeShape(shape_a, shape_b)
        if not distance.IsDone() or distance.NbSolution() == 0:
            raise ValueError(f"最小距离计算失败：{first.prim_path}，{second.prim_path}")
        gap = distance.Value() * 0.001
        if volume > volume_tolerance_m3:
            classification = "interference"
        elif gap <= length_tolerance_m:
            classification = "contact"
        else:
            continue
        findings.append({
            "part_a": first.prim_path, "part_b": second.prim_path, "classification": classification,
            "common_volume_m3": volume, "distance_m": gap,
            "point_a_m": _coordinates(distance.PointOnShape1(1)),
            "point_b_m": _coordinates(distance.PointOnShape2(1)),
        })
    known_meshes = {part.prim_path + "/Geometry" for part in data.parts}
    unmapped = sorted(str(prim.GetPath()) for prim in Usd.PrimRange.Stage(stage, Usd.TraverseInstanceProxies())
                      if prim.IsA(UsdGeom.Gprim) and str(prim.GetPath()) not in known_meshes)
    unmapped_meshes = [path for path in unmapped if stage.GetPrimAtPath(path).IsA(UsdGeom.Mesh)]
    return {
        "kind": "static_brep_interference", "engine": f"cadquery-ocp {version('cadquery-ocp')}",
        "source_sha256": data.source_sha256, "length_tolerance_m": length_tolerance_m,
        "kernel_shape_tolerance_m": kernel_tolerance_m,
        "volume_tolerance_m3": volume_tolerance_m3, "time_code": "default", "findings": findings,
        "coverage": {"part_count": len(parts), "narrow_phase_pairs": narrow_phase_pairs,
                     "bbox_separated_pairs": bbox_separated_pairs, "unmapped_mesh_paths": unmapped_meshes,
                     "unmapped_geometry_paths": unmapped,
                     "complete": not unmapped},
    }


def query_features(manifest: Path, prim_path: str, stage_path: Path | None = None,
                   asset_root: str = "/World") -> dict:
    data, stage, definitions = _load(manifest, stage_path, asset_root)
    matching = [part for part in data.parts if part.prim_path == prim_path]
    if len(matching) != 1:
        raise ValueError(f"部件未关联 BRep：{prim_path}")
    part = matching[0]
    shape = _world_shape(part, definitions[part.definition_id], stage)
    features = []
    faces = TopExp_Explorer(shape, TopAbs_FACE)
    index = 0
    while faces.More():
        face = TopoDS.Face_s(faces.Current())
        surface = BRepAdaptor_Surface(face)
        feature = {"id": f"{data.definitions[part.definition_id].sha256}:face:{index}", "face_index": index}
        if surface.GetType() == GeomAbs_Plane:
            plane = surface.Plane()
            normal = plane.Axis().Direction()
            if face.Orientation() == TopAbs_REVERSED:
                normal.Reverse()
            feature.update(type="plane", origin_m=_coordinates(plane.Location()), normal=_coordinates(normal, 1.0))
            features.append(feature)
        elif surface.GetType() == GeomAbs_Cylinder:
            cylinder = surface.Cylinder()
            feature.update(type="cylinder", origin_m=_coordinates(cylinder.Location()),
                           axis=_coordinates(cylinder.Axis().Direction(), 1.0), radius_m=cylinder.Radius() * 0.001)
            features.append(feature)
        faces.Next()
        index += 1
    return {"prim_path": prim_path, "coordinate_system": "world", "length_unit": "m",
            "brep_sha256": data.definitions[part.definition_id].sha256, "face_count": index,
            "features": features}
