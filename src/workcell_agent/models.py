import math
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

Number = Annotated[float, Field(allow_inf_nan=False)]
Positive = Annotated[Number, Field(gt=0)]
NonNegative = Annotated[Number, Field(ge=0)]
Unit = Annotated[Number, Field(ge=0, le=1)]
Vector = tuple[Number, Number, Number]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class MaterialSpec(StrictModel):
    prim_paths: list[str] = Field(min_length=1)
    color: tuple[Unit, Unit, Unit] = (0.5, 0.5, 0.5)
    metallic: Unit = 0
    roughness: Unit = 0.5
    opacity: Unit = 1
    texture: str | None = None


class PhysicsSpec(StrictModel):
    prim_path: str
    mass_kg: Positive
    diagonal_inertia: tuple[Positive, Positive, Positive] | None = None
    static_friction: NonNegative = 0.5
    dynamic_friction: NonNegative = 0.5
    restitution: Unit = 0
    collision: Literal["convexHull", "convexDecomposition", "none"] = "convexHull"
    kinematic: bool = False

    @model_validator(mode="after")
    def validate_physics(self):
        if self.diagonal_inertia and max(self.diagonal_inertia) > sum(self.diagonal_inertia) / 2:
            raise ValueError("惯量必须满足三角不等式")
        return self


class JointSpec(StrictModel):
    path: str
    body0: str | None = None
    body1: str
    kind: Literal["fixed", "revolute", "prismatic"] = "revolute"
    anchor_m: Vector = (0, 0, 0)
    axis: Vector = (1, 0, 0)
    limits: tuple[Number, Number] = (-math.pi, math.pi)
    stiffness: NonNegative = 1000
    damping: NonNegative = 100
    max_force: Positive = 10000
    articulation_root: str | None = None

    @model_validator(mode="after")
    def validate_joint(self):
        if sum(value * value for value in self.axis) < 1e-24:
            raise ValueError("关节轴线长度必须大于零")
        if self.limits[0] > self.limits[1]:
            raise ValueError("限位下限不能超过上限")
        if self.body0 == self.body1:
            raise ValueError("关节需要不同的部件")
        return self


Operation = Literal[
    "environment", "inspect_scene", "get_selection", "save_project", "convert_step",
    "import_asset", "set_material", "set_physics", "create_joint", "validate_asset",
    "query_features", "check_interference", "start_motion", "pause_motion",
    "resume_motion", "stop_motion", "reset_motion", "motion_status", "check_motion", "validation_rules",
]
READ_OPERATIONS = {"environment", "inspect_scene", "get_selection", "motion_status",
                   "validate_asset", "validation_rules", "query_features", "check_interference", "convert_step"}


class OperationRequest(StrictModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=128)
    operation: Operation
    scene_revision: str | None = None
    parameters: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_revision(self):
        if self.operation not in READ_OPERATIONS and not self.scene_revision:
            raise ValueError("场景修改需要 scene_revision")
        return self
