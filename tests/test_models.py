import pytest
from pydantic import ValidationError

from workcell_agent.models import OperationRequest, MaterialSpec, PhysicsSpec, JointSpec


def test_invalid_input_rejected():
    with pytest.raises(ValidationError):
        OperationRequest(operation="execute_python", parameters={})
    with pytest.raises(ValidationError):
        MaterialSpec(prim_paths=["/World/A"], color=[1, float("nan"), 0])
    with pytest.raises(ValidationError):
        PhysicsSpec(prim_path="/World/A", mass_kg=-1)
    with pytest.raises(ValidationError):
        JointSpec(path="/World/J", body0="/World/A", body1="/World/B", axis=[0, 0, 0])


def test_mutation_requires_revision():
    with pytest.raises(ValidationError):
        OperationRequest(operation="set_material", parameters={})
    assert OperationRequest(operation="inspect_scene").scene_revision is None


def test_inertia_must_be_physically_possible():
    with pytest.raises(ValidationError):
        PhysicsSpec(prim_path="/World/A", mass_kg=1, diagonal_inertia=[1, 1, 5])
