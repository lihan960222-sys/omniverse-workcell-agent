import asyncio

import httpx
import pytest
from aiohttp import web
from pxr import Usd, UsdGeom

from workcell_agent.bridge import create_app
from workcell_agent.dispatch import Dispatcher
from workcell_agent.scene import SceneSession


@pytest.fixture
async def server(tmp_path):
    stage = Usd.Stage.CreateNew(str(tmp_path / "source.usda"))
    UsdGeom.SetStageMetersPerUnit(stage, 1)
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Cube.Define(stage, "/World/Cube")
    stage.GetRootLayer().Save()
    session = SceneSession(stage, tmp_path / "project")
    dispatcher = Dispatcher(session)
    app = create_app(dispatcher, "test-session-secret")
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}",
                                 headers={"Authorization": "Bearer test-session-secret"}) as client:
        yield client, session
    await runner.cleanup()
    session.close()


async def completed(client, job_id):
    for _ in range(100):
        response = await client.get(f"/jobs/{job_id}")
        response.raise_for_status()
        job = response.json()
        if job["status"] not in ("queued", "running"):
            return job
        await asyncio.sleep(0.01)
    pytest.fail("真实场景操作未按时完成")


async def test_auth_and_real_scene_operation(server):
    client, session = server
    assert (await client.get("/health", headers={"Authorization": "wrong"})).status_code == 401
    response = await client.post("/jobs", json={"operation": "inspect_scene"})
    result = await completed(client, response.json()["job_id"])
    assert result["status"] == "succeeded"
    assert "/World/Cube" in [prim["path"] for prim in result["result"]["prims"]]
    payload = {"operation": "set_material", "request_id": "once", "scene_revision": session.revision,
               "parameters": {"prim_paths": ["/World/Cube"], "color": [1, 0, 0]}}
    first = await client.post("/jobs", json=payload)
    await completed(client, first.json()["job_id"])
    second = await client.post("/jobs", json=payload)
    assert second.json()["job_id"] == first.json()["job_id"]
    assert session.stage.GetPrimAtPath("/World/Cube").HasRelationship("material:binding")
    payload["parameters"]["color"] = [0, 1, 0]
    assert (await client.post("/jobs", json=payload)).status_code == 409


async def test_invalid_and_stale_requests_do_not_change_scene(server):
    client, session = server
    assert (await client.post("/jobs", json={"operation": "execute_python"})).status_code == 422
    payload = {"operation": "set_physics", "scene_revision": "old",
               "parameters": {"prim_path": "/World/Cube", "mass_kg": 1}}
    response = await client.post("/jobs", json=payload)
    job = await completed(client, response.json()["job_id"])
    assert job["status"] == "failed"
    assert "scene_revision" in job["error"]
    assert not session.stage.GetPrimAtPath("/World/Cube").HasAttribute("physics:mass")


async def test_unsupported_runtime_is_failed(server):
    client, session = server
    response = await client.post("/jobs", json={"operation": "validate_asset"})
    job = await completed(client, response.json()["job_id"])
    assert job["status"] == "failed"
    assert "Isaac Sim" in job["error"]


async def test_cancel_queued_job_preserves_real_scene(server):
    from workcell_agent.bridge import JobManager
    from workcell_agent.models import OperationRequest

    _, session = server
    manager = JobManager(Dispatcher(session))
    before = session.stage.Flatten().ExportToString()
    record = manager.submit(OperationRequest(operation="set_material", scene_revision=session.revision,
                                              parameters={"prim_paths": ["/World/Cube"], "color": [1, 0, 0]}))
    manager.cancel(record["job_id"])
    await manager.close()
    assert record["status"] == "cancelled"
    assert session.stage.Flatten().ExportToString() == before


async def test_import_converts_units_and_rejects_unresolved_reference(server, tmp_path):
    from pxr import Gf
    client, session = server
    asset = Usd.Stage.CreateNew(str(tmp_path / "millimeters.usda"))
    UsdGeom.SetStageMetersPerUnit(asset, 0.001)
    UsdGeom.SetStageUpAxis(asset, UsdGeom.GetStageUpAxis(session.stage))
    root = UsdGeom.Xform.Define(asset, "/Asset")
    asset.SetDefaultPrim(root.GetPrim())
    UsdGeom.Cube.Define(asset, "/Asset/Cube").CreateSizeAttr(100)
    asset.GetRootLayer().Save()
    payload = {"operation": "import_asset", "scene_revision": session.revision,
               "parameters": {"path": str(tmp_path / "millimeters.usda")}}
    response = await client.post("/jobs", json=payload)
    job = await completed(client, response.json()["job_id"])
    assert job["status"] == "succeeded", job
    matrix = UsdGeom.XformCache().GetLocalToWorldTransform(session.stage.GetPrimAtPath("/World/Imported/Cube"))
    assert (matrix.Transform(Gf.Vec3d(50, 0, 0)) - matrix.Transform(Gf.Vec3d(-50, 0, 0))).GetLength() == pytest.approx(0.1)
    invalid = Usd.Stage.CreateNew(str(tmp_path / "invalid.usda"))
    UsdGeom.Xform.Define(invalid, "/NoDefault")
    invalid.GetRootLayer().Save()
    payload["scene_revision"] = session.revision
    payload["parameters"] = {"path": str(tmp_path / "invalid.usda"), "prim_path": "/World/Invalid"}
    response = await client.post("/jobs", json=payload)
    job = await completed(client, response.json()["job_id"])
    assert job["status"] == "failed"
    assert not session.stage.GetPrimAtPath("/World/Invalid")
