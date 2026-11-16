import json
from pathlib import Path

import pytest
from OCP.BRep import BRep_Builder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS_Compound
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt, gp_Trsf, gp_Vec
from pxr import Gf, Usd, UsdGeom


def write_step(path: Path, shapes, positions, *, nested=False):
    document = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    XCAFDoc_DocumentTool.SetLengthUnit_s(document, 0.001)
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    compound = TopoDS_Compound()
    BRep_Builder().MakeCompound(compound)
    root = shape_tool.AddShape(compound, True)
    TDataStd_Name.Set_s(root, TCollection_ExtendedString("Workcell"))
    if nested:
        compound = TopoDS_Compound()
        BRep_Builder().MakeCompound(compound)
        assembly = shape_tool.AddShape(compound, True)
        TDataStd_Name.Set_s(assembly, TCollection_ExtendedString("Subassembly"))
        transform = gp_Trsf()
        transform.SetTranslation(gp_Vec(100, 0, 0))
        shape_tool.AddComponent(root, assembly, TopLoc_Location(transform))
    else:
        assembly = root
    labels = []
    for index, shape in enumerate(shapes):
        label = shape_tool.AddShape(shape, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(f"Part_{index}"))
        labels.append(label)
    for index, (definition, position) in enumerate(positions):
        transform = gp_Trsf()
        transform.SetTranslation(gp_Vec(*position))
        label = shape_tool.AddComponent(assembly, labels[definition], TopLoc_Location(transform))
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(f"Instance_{index}"))
    shape_tool.UpdateAssemblies()
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    writer = STEPCAFControl_Writer()
    assert writer.Transfer(document, STEPControl_AsIs)
    assert writer.Write(str(path)) == IFSelect_RetDone


def test_step_preserves_instances_hierarchy_and_meter_coordinates(tmp_path):
    from workcell_agent.geometry import convert_step

    source = tmp_path / "装配 model.stp"
    write_step(source, [BRepPrimAPI_MakeBox(10, 20, 30).Shape()],
               [(0, (0, 0, 0)), (0, (40, 0, 0))], nested=True)
    result = convert_step(source, tmp_path / "converted")
    manifest = json.loads(Path(result["geometry_manifest"]).read_text(encoding="utf-8"))
    assert len(manifest["parts"]) == 2
    assert len(manifest["definitions"]) == 1
    stage = Usd.Stage.Open(result["usd_path"])
    assert UsdGeom.GetStageMetersPerUnit(stage) == 1
    paths = [part["prim_path"] for part in manifest["parts"]]
    assert all(stage.GetPrimAtPath(path).IsInstance() for path in paths)
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    bounds = [cache.ComputeWorldBound(stage.GetPrimAtPath(path)).ComputeAlignedRange() for path in paths]
    assert sorted(bound.GetMin()[0] for bound in bounds) == pytest.approx([0.1, 0.14], abs=1e-7)
    assert tuple(bounds[0].GetSize()) == pytest.approx((0.01, 0.02, 0.03), abs=1e-7)
    assert source.is_file()


@pytest.mark.parametrize("offset,classification,volume,distance", [
    (20, None, 0, None),
    (10, "contact", 0, 0),
    (5, "interference", 5e-7, 0),
    (10.0005, "contact", 0, 5e-7),
    (9.9999, "contact", 1e-11, 0),
])
def test_real_solids_classify_interference_and_contact(tmp_path, offset, classification, volume, distance):
    from workcell_agent.geometry import check_interference, convert_step

    source = tmp_path / "boxes.stp"
    write_step(source, [BRepPrimAPI_MakeBox(10, 10, 10).Shape()],
               [(0, (0, 0, 0)), (0, (offset, 0, 0))])
    converted = convert_step(source, tmp_path / "converted")
    result = check_interference(Path(converted["geometry_manifest"]), volume_tolerance_m3=2e-11)
    assert result["coverage"]["part_count"] == 2
    assert result["coverage"]["complete"]
    if classification is None:
        assert result["findings"] == []
        assert result["coverage"]["bbox_separated_pairs"] == 1
    else:
        assert len(result["findings"]) == 1
        finding = result["findings"][0]
        assert finding["classification"] == classification
        assert finding["common_volume_m3"] == pytest.approx(volume, abs=1e-13)
        assert finding["distance_m"] == pytest.approx(distance, abs=1e-8)


def test_contained_solid_has_common_volume(tmp_path):
    from workcell_agent.geometry import check_interference, convert_step

    source = tmp_path / "contained.stp"
    write_step(source, [BRepPrimAPI_MakeBox(10, 10, 10).Shape(), BRepPrimAPI_MakeBox(2, 2, 2).Shape()],
               [(0, (0, 0, 0)), (1, (4, 4, 4))])
    converted = convert_step(source, tmp_path / "converted")
    finding = check_interference(Path(converted["geometry_manifest"]))["findings"][0]
    assert finding["classification"] == "interference"
    assert finding["common_volume_m3"] == pytest.approx(8e-9)


def test_overlapping_bounds_do_not_claim_solid_interference(tmp_path):
    from workcell_agent.geometry import check_interference, convert_step

    source = tmp_path / "spheres.stp"
    write_step(source, [BRepPrimAPI_MakeSphere(1).Shape()],
               [(0, (0, 0, 0)), (0, (1.5, 1.5, 0))])
    converted = convert_step(source, tmp_path / "converted")
    result = check_interference(Path(converted["geometry_manifest"]))
    assert result["coverage"]["narrow_phase_pairs"] == 1
    assert result["findings"] == []


def test_interference_uses_updated_usd_transform_and_reports_unmapped_mesh(tmp_path):
    from workcell_agent.geometry import check_interference, convert_step

    source = tmp_path / "moving.stp"
    write_step(source, [BRepPrimAPI_MakeBox(10, 10, 10).Shape()],
               [(0, (0, 0, 0)), (0, (20, 0, 0))])
    converted = convert_step(source, tmp_path / "converted")
    manifest_path = Path(converted["geometry_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stage = Usd.Stage.Open(converted["usd_path"])
    moving = stage.GetPrimAtPath(manifest["parts"][1]["prim_path"])
    UsdGeom.Xformable(moving).GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetTranslate(Gf.Vec3d(0.005, 0, 0)))
    UsdGeom.Mesh.Define(stage, "/World/Unmapped")
    stage.GetRootLayer().Save()
    result = check_interference(manifest_path, stage_path=Path(converted["usd_path"]))
    assert result["findings"][0]["common_volume_m3"] == pytest.approx(5e-7)
    assert not result["coverage"]["complete"]
    assert result["coverage"]["unmapped_mesh_paths"] == ["/World/Unmapped"]


def test_cylinder_and_plane_features_are_in_world_meters(tmp_path):
    from workcell_agent.geometry import convert_step, query_features

    source = tmp_path / "cylinder.stp"
    write_step(source, [BRepPrimAPI_MakeCylinder(5, 20).Shape()], [(0, (10, 0, 0))])
    converted = convert_step(source, tmp_path / "converted")
    manifest_path = Path(converted["geometry_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = query_features(manifest_path, manifest["parts"][0]["prim_path"])
    cylinder = next(feature for feature in result["features"] if feature["type"] == "cylinder")
    assert cylinder["radius_m"] == pytest.approx(0.005)
    assert cylinder["origin_m"] == pytest.approx([0.01, 0, 0])
    assert cylinder["axis"] == pytest.approx([0, 0, 1])
    assert len([feature for feature in result["features"] if feature["type"] == "plane"]) == 2


def test_geometry_rejects_changed_brep_and_invalid_tolerance(tmp_path):
    from workcell_agent.geometry import check_interference, convert_step

    source = tmp_path / "box.stp"
    write_step(source, [BRepPrimAPI_MakeBox(10, 10, 10).Shape()], [(0, (0, 0, 0))])
    converted = convert_step(source, tmp_path / "converted")
    manifest_path = Path(converted["geometry_manifest"])
    with pytest.raises(ValueError):
        check_interference(manifest_path, length_tolerance_m=float("nan"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    definition = next(iter(manifest["definitions"].values()))
    (manifest_path.parent / definition["brep_file"]).write_text("modified", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        check_interference(manifest_path)


def test_conversion_does_not_overwrite_existing_output(tmp_path):
    from workcell_agent.geometry import convert_step

    source = tmp_path / "box.stp"
    write_step(source, [BRepPrimAPI_MakeBox(10, 10, 10).Shape()], [(0, (0, 0, 0))])
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        convert_step(source, target)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_modified_mesh_cannot_reuse_original_brep_mapping(tmp_path):
    from workcell_agent.geometry import check_interference, convert_step

    source = tmp_path / "box.stp"
    write_step(source, [BRepPrimAPI_MakeBox(10, 10, 10).Shape()], [(0, (0, 0, 0))])
    converted = convert_step(source, tmp_path / "converted")
    manifest_path = Path(converted["geometry_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stage = Usd.Stage.Open(converted["usd_path"])
    part_path = manifest["parts"][0]["prim_path"]
    stage.GetPrimAtPath(part_path).SetInstanceable(False)
    mesh = UsdGeom.Mesh(stage.GetPrimAtPath(part_path + "/Geometry"))
    points = mesh.GetPointsAttr().Get()
    points[0] = Gf.Vec3f(10, 10, 10)
    mesh.GetPointsAttr().Set(points)
    stage.GetRootLayer().Save()
    with pytest.raises(ValueError, match="Mesh"):
        check_interference(manifest_path)


def test_unmapped_usd_primitive_keeps_coverage_incomplete(tmp_path):
    from workcell_agent.geometry import check_interference, convert_step

    source = tmp_path / "box.stp"
    write_step(source, [BRepPrimAPI_MakeBox(10, 10, 10).Shape()], [(0, (0, 0, 0))])
    converted = convert_step(source, tmp_path / "converted")
    stage = Usd.Stage.Open(converted["usd_path"])
    UsdGeom.Cube.Define(stage, "/World/ExtraCube")
    stage.GetRootLayer().Save()
    result = check_interference(Path(converted["geometry_manifest"]))
    assert not result["coverage"]["complete"]
    assert "/World/ExtraCube" in result["coverage"]["unmapped_geometry_paths"]


def test_open_sheet_cannot_pass_volume_interference_check(tmp_path):
    from workcell_agent.geometry import check_interference, convert_step

    source = tmp_path / "sheet.stp"
    face = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(0, 0, 1)), 0, 10, 0, 10).Face()
    write_step(source, [face], [(0, (0, 0, 0))])
    converted = convert_step(source, tmp_path / "converted")
    with pytest.raises(ValueError, match="封闭实体"):
        check_interference(Path(converted["geometry_manifest"]))


def test_requested_tolerance_below_kernel_accuracy_is_rejected(tmp_path):
    from workcell_agent.geometry import check_interference, convert_step

    source = tmp_path / "box.stp"
    write_step(source, [BRepPrimAPI_MakeBox(10, 10, 10).Shape()], [(0, (0, 0, 0))])
    converted = convert_step(source, tmp_path / "converted")
    with pytest.raises(ValueError, match="容差"):
        check_interference(Path(converted["geometry_manifest"]), length_tolerance_m=1e-12)


def test_feature_query_tracks_parent_rotation_and_rejects_nonuniform_scale(tmp_path):
    from workcell_agent.geometry import convert_step, query_features

    source = tmp_path / "cylinder.stp"
    write_step(source, [BRepPrimAPI_MakeCylinder(5, 20).Shape()], [(0, (10, 0, 0))])
    converted = convert_step(source, tmp_path / "converted")
    manifest_path = Path(converted["geometry_manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    part_path = manifest["parts"][0]["prim_path"]
    stage = Usd.Stage.Open(converted["usd_path"])
    parent = UsdGeom.Xformable(stage.GetPrimAtPath(part_path).GetParent())
    operation = parent.GetOrderedXformOps()[0]
    operation.Set(Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(1, 0, 0), 90)))
    stage.GetRootLayer().Save()
    cylinder = next(feature for feature in query_features(manifest_path, part_path)["features"]
                    if feature["type"] == "cylinder")
    assert cylinder["axis"] == pytest.approx([0, -1, 0], abs=1e-12)
    operation.Set(Gf.Matrix4d().SetScale(Gf.Vec3d(2, 1, 1)))
    stage.GetRootLayer().Save()
    with pytest.raises(ValueError, match="均匀缩放"):
        query_features(manifest_path, part_path)
