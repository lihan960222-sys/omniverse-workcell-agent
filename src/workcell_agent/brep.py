import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess

from pxr import Gf, Plug, Usd, UsdGeom


SOURCE_COMMIT = "3fd5b9548d19aa8c12c29bc9637a96d42a06f8a5"
SCHEMA_DIRECTORY = Path(__file__).parent / "resources/omniSolid"


def register_schema():
    Plug.Registry().RegisterPlugins(str(SCHEMA_DIRECTORY))
    if not Usd.SchemaRegistry().GetTypeFromSchemaTypeName("BrepArray"):
        raise RuntimeError("omniSolid schema 未注册，请使用项目启动脚本重新启动 Omniverse")


def sdk_root():
    return Path(os.environ.get("WORKCELL_BREP_ROOT", Path(__file__).resolve().parents[2] / ".work/usd-brep-sdk")).resolve()


def sdk_paths():
    root = sdk_root()
    platform = "windows-x86_64" if os.name == "nt" else "linux-x86_64"
    binary = root / "_build" / platform / "release"
    executable = binary / ("occt_to_usd.exe" if os.name == "nt" else "occt_to_usd")
    schema = root / "_build/schema/omniSolid/resources"
    return root, binary, executable, schema


def sdk_status():
    root, _, executable, schema = sdk_paths()
    record = root / "workcell-installation.json"
    missing = [str(path) for path in (executable, schema / "plugInfo.json", schema / "generatedSchema.usda", record)
               if not path.is_file()]
    result = {"installed": False, "root": str(root), "source_commit": SOURCE_COMMIT, "missing": missing}
    if not missing:
        evidence = json.loads(record.read_text(encoding="utf-8"))
        result["installed"] = (evidence["source_commit"] == SOURCE_COMMIT
                               and evidence["converter_sha256"] == hashlib.sha256(executable.read_bytes()).hexdigest()
                               and evidence["brep_array_count"] > 0)
        result["verification"] = evidence
    return result


def convert_brep(source, destination):
    root, binary, executable, schema = sdk_paths()
    if not executable.is_file():
        raise RuntimeError("请先完成 install_usd_brep，官方 occt_to_usd 转换器不存在")
    environment = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "PXR_PLUGINPATH_NAME", "LD_PRELOAD"):
        environment.pop(key, None)
    environment["OMNISOLID_PLUGIN_PATH"] = str(schema)
    libraries = [binary, binary / "extraLibs", root / "_build/target-deps/usd/release/lib",
                 root / "_build/target-deps/python/lib"]
    environment["LD_LIBRARY_PATH"] = os.pathsep.join(str(path) for path in libraries)
    environment["PATH"] = os.pathsep.join([*(str(path) for path in libraries), environment.get("PATH", "")])
    subprocess.run([str(executable), str(source), str(destination)], check=True, env=environment)
    stage = Usd.Stage.Open(str(destination))
    prims = [prim for prim in stage.Traverse() if prim.GetTypeName() == "BrepArray"]
    if len(prims) != 1:
        raise ValueError(f"官方转换输出需要一个 BrepArray，实际为 {len(prims)}")
    return str(prims[0].GetPath())


def verify_installation():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepTools import BRepTools

    register_schema()
    root, _, executable, schema = sdk_paths()
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    if commit != SOURCE_COMMIT:
        raise ValueError("USD BRep 源码版本与项目配置不一致")
    for name in ("plugInfo.json", "generatedSchema.usda"):
        if (schema / name).read_bytes() != (SCHEMA_DIRECTORY / name).read_bytes():
            raise ValueError(f"USD BRep schema 版本不一致：{name}")
    probe = root / ".work/workcell-probe"
    probe.mkdir(parents=True, exist_ok=True)
    source, destination = probe / "box.brep", probe / "box.usda"
    if not BRepTools.Write_s(BRepPrimAPI_MakeBox(10, 20, 30).Shape(), str(source)):
        raise OSError("安装验证 BRep 写入失败")
    path = convert_brep(source, destination)
    stage = Usd.Stage.Open(str(destination))
    prim = stage.GetPrimAtPath(path)
    face_types = prim.GetAttribute("face:surfaceType").Get()
    extent = prim.GetAttribute("brep:extent").Get()
    if not face_types or len(face_types) != 6 or not extent or len(extent) != 2:
        raise ValueError("USD BRep 安装验证需要完整的六面 box 数据")
    size = extent[1] - extent[0]
    if not all(math.isclose(value, expected, rel_tol=1e-6, abs_tol=1e-5)
               for value, expected in zip(size, (10, 20, 30))):
        raise ValueError(f"USD BRep 安装验证的毫米尺寸不正确：{size}")
    result = {"source_commit": commit, "converter_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
              "brep_array_count": 1, "probe_usd": str(destination), "probe_prim": path,
              "probe_face_count": len(face_types), "probe_size_mm": list(size)}
    (root / "workcell-installation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def convert_step_brep(source, output_directory):
    from .geometry import convert_step, GeometryManifest

    if not sdk_status()["installed"]:
        raise RuntimeError("USD BRep 尚未完成安装验证，请执行 install_usd_brep")
    register_schema()
    result = convert_step(Path(source), Path(output_directory))
    manifest_path = Path(result["geometry_manifest"])
    manifest = GeometryManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    meshes = Usd.Stage.Open(str(manifest_path.parent / manifest.mesh_file))
    for identifier, definition in manifest.definitions.items():
        source = manifest_path.parent / definition.brep_file
        target = source.with_suffix(".usdc")
        root = convert_brep(source, target)
        prim = meshes.OverridePrim(f"/{identifier}/BRep")
        prim.GetReferences().AddReference(target.relative_to(manifest_path.parent).as_posix(), root)
        UsdGeom.Xformable(prim).AddScaleOp().Set(Gf.Vec3f(0.001))
        UsdGeom.Imageable(prim).CreatePurposeAttr("guide")
        definition.usd_brep_file = target.relative_to(manifest_path.parent).as_posix()
        definition.usd_brep_sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    meshes.GetRootLayer().Save()
    manifest.mesh_sha256 = hashlib.sha256((manifest_path.parent / manifest.mesh_file).read_bytes()).hexdigest()
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return {**result, "representation": "BrepArray+Mesh", "brep_definition_count": len(manifest.definitions),
            "source_commit": SOURCE_COMMIT, "parts": [part.model_dump() for part in manifest.parts]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["verify-installation"])
    parser.parse_args()
    print(json.dumps(verify_installation(), ensure_ascii=False))


if __name__ == "__main__":
    main()
