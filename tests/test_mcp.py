import asyncio
import json
import socket
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import pytest
from aiohttp import web
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pxr import Usd, UsdGeom

from workcell_agent.bridge import create_app
from workcell_agent.dispatch import Dispatcher
from workcell_agent.scene import SceneSession


@asynccontextmanager
async def mcp_connection(tmp_path, url):
    root = Path(__file__).resolve().parents[1]
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "workcell_agent.mcp_server"],
        cwd=tmp_path,
        env={"PYTHONPATH": str(root / "src"), "PYTHONDONTWRITEBYTECODE": "1",
             "WORKCELL_URL": url, "WORKCELL_TOKEN": "test-mcp-session-secret"},
    )
    with (tmp_path / "mcp-stderr.log").open("w", encoding="utf-8") as error_log:
        async with asyncio.timeout(30):
            async with stdio_client(parameters, errlog=error_log) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as client:
                    await client.initialize()
                    yield client


async def test_stdio_lists_tools_and_returns_motion_schema(tmp_path):
    async with mcp_connection(tmp_path, "http://127.0.0.1:8765") as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        assert {"connection_status", "submit_operation", "get_job", "cancel_job", "operation_schema"} <= names
        schema = await client.call_tool("operation_schema", {"operation": "start_motion"})
        assert not schema.isError
        schema_data = json.loads(schema.content[0].text)
        assert {"initial_positions", "actions"} <= set(schema_data["required"])
        definition = schema_data["$defs"]["MotionAction"]
        assert {"joint_path", "start", "target", "max_velocity", "max_acceleration"} <= set(definition["required"])
        for operation, required in (("import_step", "source"), ("auto_material", "prim_paths"),
                                    ("record_video", "prim_path")):
            schema = await client.call_tool("operation_schema", {"operation": operation})
            assert not schema.isError
            assert required in json.loads(schema.content[0].text)["required"]


async def test_unreachable_bridge_returns_mcp_error(tmp_path):
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{reserved.getsockname()[1]}"
        async with mcp_connection(tmp_path, url) as client:
            result = await client.call_tool("connection_status", {})
            assert result.isError
            assert result.structuredContent is None
            assert result.content


@pytest.fixture
async def scene_bridge(tmp_path):
    stage = Usd.Stage.CreateNew(str(tmp_path / "source.usda"))
    UsdGeom.SetStageMetersPerUnit(stage, 0.001)
    UsdGeom.Xform.Define(stage, "/World")
    UsdGeom.Cube.Define(stage, "/World/Slide")
    stage.GetRootLayer().Save()
    session = SceneSession(stage, tmp_path / "project")
    runner = web.AppRunner(create_app(Dispatcher(session), "test-mcp-session-secret"))
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", session
    finally:
        await runner.cleanup()
        session.close()


async def test_stdio_reads_real_usd_scene_through_bridge(tmp_path, scene_bridge):
    url, session = scene_bridge
    async with mcp_connection(tmp_path, url) as client:
        health = await client.call_tool("connection_status", {})
        assert not health.isError
        assert json.loads(health.content[0].text)["scene_revision"] == session.revision
        submitted = await client.call_tool("submit_operation", {"operation": "inspect_scene"})
        assert not submitted.isError
        job_id = json.loads(submitted.content[0].text)["job_id"]
        while True:
            response = await client.call_tool("get_job", {"job_id": job_id})
            assert not response.isError
            job = json.loads(response.content[0].text)
            if job["status"] not in {"queued", "running"}:
                break
            await asyncio.sleep(0.01)
        assert job["status"] == "succeeded", job["error"]
        assert job["result"]["meters_per_unit"] == 0.001
        assert {prim["path"] for prim in job["result"]["prims"]} == {"/World", "/World/Slide"}
