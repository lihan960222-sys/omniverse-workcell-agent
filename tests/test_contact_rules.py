import pytest

from workcell_agent.motion import MotionPlan


def make_plan():
    return MotionPlan.model_validate({
        "initial_positions": {"/Joint": 0},
        "actions": [{"id": "slide", "joint_path": "/Joint", "start": 0, "target": 1,
                     "max_velocity": 1, "max_acceleration": 1, "timeout": 10}],
        "allowed_contacts": [{"part_a": "/Clamp", "part_b": "/Workpiece",
                              "max_penetration_m": 0.0001, "reason": "夹持接触"}],
    })


def test_contact_rules_use_pair_and_penetration():
    from workcell_agent.motion import classify_contact
    plan = make_plan()
    assert classify_contact(plan, "/Clamp", "/Workpiece", -0.00005) == "allowed_contact"
    assert classify_contact(plan, "/Workpiece", "/Clamp", 0) == "allowed_contact"
    assert classify_contact(plan, "/Clamp", "/Workpiece", -0.002) == "excess_penetration"
    assert classify_contact(plan, "/Clamp", "/Obstacle", 0) == "unexpected_contact"
    with pytest.raises(ValueError):
        classify_contact(plan, "/Clamp", "/Workpiece", float("nan"))


def test_invalid_contact_rule_rejected():
    data = make_plan().model_dump()
    data["allowed_contacts"][0]["part_b"] = "/Clamp"
    with pytest.raises(ValueError):
        MotionPlan.model_validate(data)
