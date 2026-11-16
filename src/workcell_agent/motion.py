import math
from dataclasses import dataclass
from graphlib import TopologicalSorter

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, field_validator, model_validator


class MotionAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    joint_path: str = Field(min_length=2)
    start: FiniteFloat
    target: FiniteFloat
    max_velocity: FiniteFloat = Field(gt=0)
    max_acceleration: FiniteFloat = Field(gt=0)
    depends_on: list[str] = Field(default_factory=list)
    tolerance: FiniteFloat = Field(default=1e-4, gt=0)
    timeout: FiniteFloat = Field(gt=0)

    @field_validator("joint_path")
    @classmethod
    def absolute_joint_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("joint_path must be absolute")
        return value


class ContactRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    part_a: str = Field(min_length=2)
    part_b: str = Field(min_length=2)
    max_penetration_m: FiniteFloat = Field(ge=0)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_pair(self):
        if self.part_a == self.part_b or not all(path.startswith("/") for path in (self.part_a, self.part_b)):
            raise ValueError("允许接触规则需要两个不同的绝对部件路径")
        return self


class MotionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_positions: dict[str, FiniteFloat]
    actions: list[MotionAction] = Field(min_length=1)
    physics_hz: int = Field(default=120, ge=30, le=1000)
    enable_ccd: bool = True
    allowed_contacts: list[ContactRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rules(self):
        pairs = [frozenset((rule.part_a, rule.part_b)) for rule in self.allowed_contacts]
        if len(set(pairs)) != len(pairs):
            raise ValueError("同一接触对象组合只能定义一条规则")
        return self


def classify_contact(plan: MotionPlan, part_a: str, part_b: str, separation_m: float) -> str:
    if not math.isfinite(separation_m):
        raise ValueError("接触距离必须为有限数值")
    pair = frozenset((part_a, part_b))
    for rule in plan.allowed_contacts:
        if pair == frozenset((rule.part_a, rule.part_b)):
            return "allowed_contact" if separation_m >= -rule.max_penetration_m else "excess_penetration"
    return "unexpected_contact"


@dataclass(frozen=True)
class _ScheduledAction:
    action: MotionAction
    start_time: float
    duration: float
    acceleration_time: float
    peak_velocity: float


def _profile(action: MotionAction) -> tuple[float, float, float]:
    distance = abs(action.target - action.start)
    if not math.isfinite(distance):
        raise ValueError(f"{action.id}: distance must be finite")
    if distance == 0:
        return 0.0, 0.0, 0.0
    acceleration_time = min(
        action.max_velocity / action.max_acceleration,
        math.sqrt(distance) / math.sqrt(action.max_acceleration),
    )
    peak_velocity = action.max_acceleration * acceleration_time
    if not math.isfinite(peak_velocity) or peak_velocity <= 0:
        raise ValueError(f"{action.id}: profile requires finite positive velocity")
    duration = acceleration_time + distance / peak_velocity
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"{action.id}: duration must be finite and positive")
    if duration > action.timeout:
        raise ValueError(f"{action.id}: timeout is shorter than the planned motion")
    return acceleration_time, peak_velocity, duration


def _schedule(plan: MotionPlan) -> list[_ScheduledAction]:
    actions = {action.id: action for action in plan.actions}
    if len(actions) != len(plan.actions):
        raise ValueError("duplicate action id")
    for action in plan.actions:
        unknown = set(action.depends_on) - actions.keys()
        if unknown:
            raise ValueError(f"{action.id}: unknown dependencies: {sorted(unknown)}")
    order = TopologicalSorter({action.id: action.depends_on for action in plan.actions}).static_order()
    ancestors: dict[str, set[str]] = {}
    ends: dict[str, float] = {}
    last_by_joint: dict[str, MotionAction] = {}
    schedule = []
    for action_id in order:
        action = actions[action_id]
        predecessors = set(action.depends_on)
        for dependency in action.depends_on:
            predecessors.update(ancestors[dependency])
        ancestors[action_id] = predecessors
        previous = last_by_joint.get(action.joint_path)
        if previous is not None:
            if previous.id not in predecessors:
                raise ValueError(f"{action.joint_path}: actions must be dependency ordered")
            expected_start = previous.target
        else:
            if action.joint_path not in plan.initial_positions:
                raise ValueError(f"{action.joint_path}: initial position is required")
            expected_start = plan.initial_positions[action.joint_path]
        if abs(action.start - expected_start) > action.tolerance:
            raise ValueError(f"{action.id}: start does not match the preceding joint position")
        acceleration_time, peak_velocity, duration = _profile(action)
        start_time = max((ends[dependency] for dependency in action.depends_on), default=0.0)
        end_time = start_time + duration
        if not math.isfinite(end_time):
            raise ValueError(f"{action.id}: scheduled end time must be finite")
        schedule.append(_ScheduledAction(action, start_time, duration, acceleration_time, peak_velocity))
        ends[action_id] = end_time
        last_by_joint[action.joint_path] = action
    return schedule


def validate_motion(plan: MotionPlan) -> None:
    _schedule(plan)


def motion_duration(plan: MotionPlan) -> float:
    return max(item.start_time + item.duration for item in _schedule(plan))


def sample_motion(plan: MotionPlan, time_s: float) -> dict[str, float]:
    if not math.isfinite(time_s) or time_s < 0:
        raise ValueError("sample time must be finite and nonnegative")
    positions = dict(plan.initial_positions)
    for item in _schedule(plan):
        elapsed = time_s - item.start_time
        if elapsed < 0:
            continue
        action = item.action
        if elapsed >= item.duration:
            positions[action.joint_path] = action.target
            continue
        distance = abs(action.target - action.start)
        if elapsed < item.acceleration_time:
            travel = 0.5 * (action.max_acceleration * elapsed) * elapsed
        elif elapsed < item.duration - item.acceleration_time:
            travel = item.peak_velocity * (elapsed - 0.5 * item.acceleration_time)
        else:
            remaining = item.duration - elapsed
            travel = distance - 0.5 * (action.max_acceleration * remaining) * remaining
        positions[action.joint_path] = action.start + math.copysign(travel, action.target - action.start)
    return positions
