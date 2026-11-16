from workcell_agent.mcp_server import operation_schema
from workcell_agent.models import OperationRequest


def test_brep_operations_expose_parameters_and_revision():
    for operation in ("usd_brep_status", "install_usd_brep", "convert_step_brep"):
        assert OperationRequest(operation=operation)
        assert isinstance(operation_schema(operation), dict)
    schema = operation_schema("import_step")
    assert "source" in schema["properties"]
    request = OperationRequest(operation="import_step", scene_revision="scene:1", parameters={"source": "/part.stp"})
    assert request.scene_revision == "scene:1"
