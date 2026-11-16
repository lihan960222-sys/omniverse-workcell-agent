import os
import json
from pathlib import Path
from uuid import uuid4

from pxr import Usd, Sdf, Tf, UsdUtils, UsdGeom


class SceneSession:
    def __init__(self, stage: Usd.Stage, project_directory: Path):
        self.stage = stage
        self.directory = Path(project_directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._identity = uuid4().hex
        self._output = self.directory / f"workcell-{self._identity}.usda"
        self._counter = 0
        self.layer = Sdf.Layer.CreateAnonymous("workcell-edits.usda")
        self.stage.GetSessionLayer().subLayerPaths.insert(0, self.layer.identifier)
        self._original_target = self.stage.GetEditTarget()
        self.stage.SetEditTarget(self.layer)
        self._notice = Tf.Notice.Register(Usd.Notice.ObjectsChanged, self._changed, stage)

    def _changed(self, notice, sender):
        self._counter += 1

    @property
    def revision(self):
        return f"{self._identity}:{self._counter}"

    def require_revision(self, expected: str):
        if expected != self.revision:
            raise ValueError("scene_revision 已改变，请重新读取当前场景")

    def edit(self, expected: str, operation):
        self.require_revision(expected)
        temporary = Sdf.Layer.CreateAnonymous("workcell-transaction.usda")
        session_layer = self.stage.GetSessionLayer()
        session_layer.subLayerPaths.insert(0, temporary.identifier)
        self.stage.SetEditTarget(temporary)
        try:
            result = operation(self.stage)
            UsdUtils.StitchLayers(temporary, self.layer)
            self.layer.TransferContent(temporary)
            return result
        finally:
            self.stage.SetEditTarget(self.layer)
            session_layer.subLayerPaths.remove(temporary.identifier)

    def inspect(self):
        return {"scene_revision": self.revision,
                "root_layer": self.stage.GetRootLayer().identifier,
                "meters_per_unit": UsdGeom.GetStageMetersPerUnit(self.stage),
                "prims": [{"path": str(prim.GetPath()), "type": prim.GetTypeName(),
                           "name": prim.GetDisplayName() or prim.GetName()}
                          for prim in self.stage.Traverse()]}

    def save(self):
        source = self.stage.GetRootLayer()
        local_layers = self.stage.GetLayerStack()
        dirty_references = [layer.identifier for layer in self.stage.GetUsedLayers()
                            if layer not in local_layers and layer.dirty]
        if dirty_references:
            raise ValueError(f"外部引用 Layer 包含未保存的修改，请明确处理这些资产后保存工程: {dirty_references}")
        if any(layer.anonymous or layer.dirty for layer in self.stage.GetLayerStack(False)):
            source_path = self.directory / f"source-{self._identity}.usda"
            source_stage = Usd.Stage.Open(source, sessionLayer=Sdf.Layer.CreateAnonymous())
            saved_source = UsdUtils.FlattenLayerStack(source_stage)
            saved_source.Export(str(source_path))
        else:
            source_path = Path(source.realPath).resolve()
        edits_path = self.directory / f"edits-{self._identity}.usda"
        saved_edits = UsdUtils.FlattenLayerStack(Usd.Stage.Open(self.stage.GetSessionLayer()))
        def relative_asset(path):
            candidate = Path(path)
            if candidate.is_absolute() and candidate.is_relative_to(self.directory):
                return candidate.relative_to(self.directory).as_posix()
            return path
        UsdUtils.ModifyAssetPaths(saved_edits, relative_asset)
        saved_edits.Export(str(edits_path))
        output = self._output
        root = Sdf.Layer.CreateAnonymous("workcell.usda")
        root.subLayerPaths = [edits_path.name, Path(os.path.relpath(source_path, self.directory)).as_posix()]
        for key, value in self.stage.GetPseudoRoot().GetAllMetadata().items():
            if key not in {"subLayers", "subLayerOffsets"}:
                root.pseudoRoot.SetInfo(key, value)
        root.Export(str(output))
        project = self.directory / f"project-{self._identity}.json"
        project.write_text(json.dumps({"schema_version": 1, "usd_file": output.name,
                                       "scene_revision": self.revision,
                                       "motion_plans": [path.relative_to(self.directory).as_posix()
                                                        for path in sorted((self.directory / "motions").glob("*.json"))]},
                                      ensure_ascii=False, indent=2), encoding="utf-8")
        return {"path": str(output), "project_file": str(project), "scene_revision": self.revision}

    def close(self):
        self._notice.Revoke()
        self.stage.SetEditTarget(self._original_target)
