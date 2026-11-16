import math

import pytest
from pydantic import ValidationError

from workcell_agent.motion import MotionAction, MotionPlan, motion_duration, sample_motion, validate_motion


def action(action_id="move", joint="/World/J", start=0.0, target=1.0, **kwargs):
    return MotionAction(
        id=action_id, joint_path=joint, start=start, target=target,
        max_velocity=kwargs.pop("max_velocity", 2.0),
        max_acceleration=kwargs.pop("max_acceleration", 1.0),
        timeout=kwargs.pop("timeout", 30.0), **kwargs,
    )


def plan(*actions, initial_positions=None):
    return MotionPlan(actions=list(actions), initial_positions=initial_positions or {"/World/J": 0.0})


def test_triangular_motion_and_hold():
    movement = plan(action())
    validate_motion(movement)
    assert motion_duration(movement) == pytest.approx(2.0)
    for time_s, expected in [(0, 0), (0.5, 0.125), (1, 0.5), (1.5, 0.875), (2, 1), (10, 1)]:
        assert sample_motion(movement, time_s) == pytest.approx({"/World/J": expected})


def test_trapezoidal_motion():
    movement = plan(action(target=10.0))
    assert motion_duration(movement) == pytest.approx(7.0)
    for time_s, expected in [(1, 0.5), (2, 2), (4, 6), (5, 8), (6, 9.5), (7, 10)]:
        assert sample_motion(movement, time_s)["/World/J"] == pytest.approx(expected)


def test_negative_direction_and_stationary_joint():
    movement = plan(action(start=3, target=2), initial_positions={"/World/J": 3, "/World/Hold": 4})
    assert sample_motion(movement, 0.5) == pytest.approx({"/World/J": 2.875, "/World/Hold": 4})
    stationary = plan(action(start=0, target=0))
    assert motion_duration(stationary) == 0
    assert sample_motion(stationary, 0) == {"/World/J": 0}


def test_dependencies_parallelism_and_initial_state_are_order_independent():
    movement = plan(
        action("return", start=1, target=0, depends_on=["wait", "move"]),
        action("wait", joint="/World/K", start=2, target=12),
        action("move"),
        initial_positions={"/World/J": 0, "/World/K": 2},
    )
    assert motion_duration(movement) == pytest.approx(9)
    assert sample_motion(movement, 0) == {"/World/J": 0, "/World/K": 2}
    assert sample_motion(movement, 3) == pytest.approx({"/World/J": 1, "/World/K": 6})
    assert sample_motion(movement, 8) == pytest.approx({"/World/J": 0.5, "/World/K": 12})


def test_curve_respects_velocity_and_acceleration_limits():
    movement = plan(action(target=10))
    dt = 0.01
    positions = [sample_motion(movement, i * dt)["/World/J"] for i in range(701)]
    velocities = [(b - a) / dt for a, b in zip(positions, positions[1:])]
    accelerations = [(b - a) / dt for a, b in zip(velocities, velocities[1:])]
    assert max(abs(value) for value in velocities) <= 2.0 + 1e-8
    assert max(abs(value) for value in accelerations) <= 1.0 + 1e-8


@pytest.mark.parametrize("actions, message", [
    ([action("same"), action("same", joint="/World/K")], "duplicate"),
    ([action(depends_on=["absent"])], "unknown"),
    ([action("a", depends_on=["b"]), action("b", depends_on=["a"])], "cycle"),
    ([action("a"), action("b", start=1, target=2)], "ordered"),
    ([action("a"), action("b", start=2, target=3, depends_on=["a"])], "start"),
    ([action(timeout=1)], "timeout"),
])
def test_invalid_schedule_is_rejected(actions, message):
    with pytest.raises(ValueError, match=message):
        validate_motion(plan(*actions, initial_positions={"/World/J": 0, "/World/K": 0}))


def test_initial_state_must_exist_and_match_first_action():
    with pytest.raises(ValueError, match="initial"):
        validate_motion(MotionPlan(actions=[action()], initial_positions={}))
    with pytest.raises(ValueError, match="start"):
        validate_motion(plan(action(start=1)))


@pytest.mark.parametrize("field", ["start", "target", "max_velocity", "max_acceleration", "tolerance", "timeout"])
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_action_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        action(**{field: value})


@pytest.mark.parametrize("field", ["max_velocity", "max_acceleration", "tolerance", "timeout"])
def test_positive_parameters_are_required(field):
    with pytest.raises(ValidationError):
        action(**{field: 0})


@pytest.mark.parametrize("time_s", [-1, math.nan, math.inf, -math.inf])
def test_invalid_sample_time_is_rejected(time_s):
    with pytest.raises(ValueError, match="time"):
        sample_motion(plan(action()), time_s)


def test_unrepresentable_distance_is_rejected():
    with pytest.raises(ValueError, match="finite"):
        validate_motion(plan(action(start=-1e308, target=1e308), initial_positions={"/World/J": -1e308}))


@pytest.mark.parametrize("distance, acceleration, midpoint", [
    (1e200, 1e-200, 1e200),
    (1e-200, 1e200, 1e-200),
])
def test_representable_extreme_profiles_remain_finite(distance, acceleration, midpoint):
    movement = plan(action(target=distance, max_acceleration=acceleration, timeout=1e201))
    assert motion_duration(movement) == pytest.approx(2 * midpoint, abs=0)
    assert sample_motion(movement, midpoint)["/World/J"] == pytest.approx(0.5 * distance, abs=0)
