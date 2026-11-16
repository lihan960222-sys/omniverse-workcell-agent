import asyncio
import json
import math
from pathlib import Path

import pytest
import omni.kit.app
import omni.usd
from pxr import UsdPhysics, PhysxSchema

from workcell_agent.isaac_runtime import IsaacHost
from workcell_agent.scene import SceneSession
from workcell_agent.example import create_example


@pytest.mark.asyncio
async def test_record_video(tmp_path):
    host, session = await lifecycle_host(tmp_path)
    from omni.kit.viewport.utility import get_active_viewport
    original_camera = get_active_viewport().camera_path
    try:
        result = await host.execute("record_video", {"prim_path": "/World/Mechanism", "duration_s": 1,
                                                     "fps": 12, "width": 320, "height": 240})
        assert Path(result["video"]).stat().st_size > 0
        assert int(result["decoded"]["nb_read_frames"]) == 12
        assert not host.capture_running
        assert not host.timeline.is_playing()
        assert not session.stage.GetPrimAtPath(result["presentation_root"])
        assert get_active_viewport().camera_path == original_camera
    finally:
        await host.close()
        session.close()


@pytest.mark.asyncio
async def test_real_joint_motion_and_stop(tmp_path):
    path = create_example(tmp_path / "sample.usda")
    context = omni.usd.get_context()
    await context.open_stage_async(str(path))
    session = SceneSession(context.get_stage(), tmp_path / "project")
    host = IsaacHost(session)
    plan = {"initial_positions": {"/World/Mechanism/Slide": 0.0},
            "actions": [{"id": "move", "joint_path": "/World/Mechanism/Slide", "start": 0,
                         "target": 0.1, "max_velocity": 0.1, "max_acceleration": 0.2,
                         "timeout": 6, "tolerance": 0.002}]}
    await host.execute("start_motion", plan)
    for _ in range(1500):
        await omni.kit.app.get_app().next_update_async()
        if host.status["state"] in {"succeeded", "failed"}:
            break
    assert host.status["state"] == "succeeded", host.status
    assert host.status["positions"]["/World/Mechanism/Slide"] == pytest.approx(0.1, abs=0.002)
    await host.execute("reset_motion", {})
    await host.close()
    session.close()


@pytest.mark.asyncio
async def test_official_validation_returns_rule_coverage(tmp_path):
    path = create_example(tmp_path / "sample.usda")
    await omni.usd.get_context().open_stage_async(str(path))
    session = SceneSession(omni.usd.get_context().get_stage(), tmp_path / "project")
    host = IsaacHost(session)
    report = await host.execute("validate_asset", {"categories": ["PhysicsRigidBodies"]})
    assert report["executed_rules"]
    assert report["profile_conformance"] == "not_evaluated"
    await host.close()
    session.close()


@pytest.mark.asyncio
async def test_contacts_are_real_events(tmp_path):
    path = create_example(tmp_path / "contact.usda")
    await omni.usd.get_context().open_stage_async(str(path))
    stage = omni.usd.get_context().get_stage()
    assert stage.GetPrimAtPath("/World/Mechanism/Slider").HasAPI(UsdPhysics.RigidBodyAPI)
    session = SceneSession(stage, tmp_path / "project")
    host = IsaacHost(session)
    # 示例中障碍物位于滑台运动路径上，实际接触必须产生事件。
    plan = {"initial_positions": {"/World/Mechanism/Slide": 0.0},
            "actions": [{"id": "move", "joint_path": "/World/Mechanism/Slide", "start": 0,
                         "target": 0.3, "max_velocity": 0.1, "max_acceleration": 0.2,
                         "timeout": 8, "tolerance": 0.002}],
            "physics_hz": 120, "enable_ccd": True,
            "allowed_contacts": [{"part_a": "/World/Mechanism/Slider", "part_b": "/World/Obstacle",
                                  "max_penetration_m": 0.002, "reason": "验证滑台与静态限位的允许接触"}]}
    await host.execute("check_motion", plan)
    scene_api = PhysxSchema.PhysxSceneAPI(stage.GetPrimAtPath("/World/PhysicsScene"))
    assert scene_api.GetTimeStepsPerSecondAttr().Get() == 120
    assert scene_api.GetEnableCCDAttr().Get()
    assert PhysxSchema.PhysxRigidBodyAPI(stage.GetPrimAtPath("/World/Mechanism/Slider")).GetEnableCCDAttr().Get()
    for _ in range(2500):
        await omni.kit.app.get_app().next_update_async()
        if host.status["state"] in {"succeeded", "failed"}:
            break
    assert host.contacts
    assert host.contacts[0]["part_a"] != host.contacts[0]["part_b"]
    assert host.status["state"] in {"succeeded", "failed"}, host.status
    report = json.loads(Path(host.status["reports"]["json"]).read_text(encoding="utf-8"))
    assert report["coverage"]["allowed_contacts"] == plan["allowed_contacts"]
    assert report["coverage"]["trajectory_completed"] == (host.status["state"] == "succeeded")
    obstacle_contacts = [entry for entry in host.contacts
                         if {entry["part_a"], entry["part_b"]} == {"/World/Mechanism/Slider", "/World/Obstacle"}]
    assert obstacle_contacts
    assert all(entry["classification"] in {"allowed_contact", "excess_penetration"} for entry in obstacle_contacts)
    assert all({entry["collider0"], entry["collider1"]}
               == {"/World/Mechanism/Slider/Mesh", "/World/Obstacle"} for entry in obstacle_contacts)
    for entry in obstacle_contacts:
        for field in ("position_m", "normal", "impulse_Ns"):
            assert len(entry[field]) == 3
            assert all(math.isfinite(value) for value in entry[field])
        assert math.sqrt(sum(value * value for value in entry["normal"])) == pytest.approx(1, abs=1e-5)
        assert entry["type"] in {"CONTACT_FOUND", "CONTACT_PERSIST"}
        assert report["events"][entry["event_index"]]["type"] == entry["type"]
    assert any(any(value != 0 for value in entry["impulse_Ns"]) for entry in obstacle_contacts)
    assert report["events"] == host.contact_events
    assert report["run"]["contact_event_count"] == len(host.contact_events)
    await host.close()
    session.close()


@pytest.mark.asyncio
async def test_contact_lifecycle_preserves_lost_events(tmp_path):
    path = create_example(tmp_path / "contact-lifecycle.usda")
    await omni.usd.get_context().open_stage_async(str(path))
    session = SceneSession(omni.usd.get_context().get_stage(), tmp_path / "project")
    host = IsaacHost(session)
    # 滑台压向限位后退回，PhysX 必须报告接触开始和接触结束。
    plan = {"initial_positions": {"/World/Mechanism/Slide": 0.0},
            "actions": [{"id": "touch", "joint_path": "/World/Mechanism/Slide", "start": 0,
                         "target": 0.171, "max_velocity": 0.1, "max_acceleration": 0.2,
                         "timeout": 8, "tolerance": 0.003},
                        {"id": "retract", "joint_path": "/World/Mechanism/Slide", "start": 0.171,
                         "target": 0, "max_velocity": 0.1, "max_acceleration": 0.2,
                         "depends_on": ["touch"], "timeout": 8, "tolerance": 0.003}]}
    try:
        await host.execute("check_motion", plan)
        for _ in range(3000):
            await omni.kit.app.get_app().next_update_async()
            if host.status["state"] in {"succeeded", "failed"}:
                break
        assert host.status["state"] == "succeeded", host.status
        report = json.loads(Path(host.status["reports"]["json"]).read_text(encoding="utf-8"))
        events = [(index, event) for index, event in enumerate(report["events"])
                  if {event["part_a"], event["part_b"]}
                  == {"/World/Mechanism/Slider", "/World/Obstacle"}]
        found = [event for _, event in events if event["type"] == "CONTACT_FOUND"]
        lost = [(index, event) for index, event in events if event["type"] == "CONTACT_LOST"]
        assert found and lost, events
        assert found[0]["time_s"] < lost[-1][1]["time_s"]
        for index, event in lost:
            assert event["contact_count"] == 0
            assert {event["collider0"], event["collider1"]} == {"/World/Mechanism/Slider/Mesh", "/World/Obstacle"}
            assert not any(entry["event_index"] == index for entry in report["findings"])
        assert report["run"]["contact_count"] == len(report["findings"])
        assert report["run"]["contact_event_count"] == len(report["events"])
        await host.execute("reset_motion", {})
        assert host.contact_events == []
        assert host.contacts == []
    finally:
        await host.close()
        session.close()


def lifecycle_plan():
    return {"initial_positions": {"/World/Mechanism/Slide": 0.0},
            "actions": [{"id": "move", "joint_path": "/World/Mechanism/Slide", "start": 0,
                         "target": 0.1, "max_velocity": 0.1, "max_acceleration": 0.2,
                         "timeout": 6, "tolerance": 0.002}]}


async def lifecycle_host(tmp_path):
    path = create_example(tmp_path / "lifecycle.usda")
    context = omni.usd.get_context()
    await context.open_stage_async(str(path))
    session = SceneSession(context.get_stage(), tmp_path / "project")
    host = IsaacHost(session)
    host.timeline.stop()
    await omni.kit.app.get_app().next_update_async()
    return host, session


@pytest.mark.asyncio
async def test_start_during_running_preserves_motion(tmp_path):
    host, session = await lifecycle_host(tmp_path)
    try:
        started = await host.execute("start_motion", lifecycle_plan())
        with pytest.raises(ValueError):
            await host.execute("start_motion", lifecycle_plan())
        assert host.status["run_id"] == started["run_id"]
        assert host.status["state"] == "running"
        assert host.timeline.is_playing()
        await host.execute("pause_motion", {})
        paused_time = host.status["time_s"]
        for _ in range(3):
            await omni.kit.app.get_app().next_update_async()
        assert host.status["time_s"] == paused_time
        await host.execute("resume_motion", {})
        for _ in range(1500):
            await omni.kit.app.get_app().next_update_async()
            if host.status["state"] in {"succeeded", "failed"}:
                break
        assert host.status["state"] == "succeeded", host.status
    finally:
        await host.close()
        session.close()


@pytest.mark.asyncio
async def test_initialization_cancellation(tmp_path):
    for operation in ("stop_motion", "reset_motion", "close"):
        host, session = await lifecycle_host(tmp_path / operation)
        started = asyncio.create_task(host.execute("check_motion", lifecycle_plan()))
        try:
            await asyncio.sleep(0)
            assert host.status["state"] == "initializing"
            run_id = host.status["run_id"]
            with pytest.raises(ValueError):
                await host.execute("start_motion", lifecycle_plan())
            assert host.status["run_id"] == run_id
            assert not started.done()
            if operation == "close":
                await host.close()
            else:
                await host.execute(operation, {})
            with pytest.raises(asyncio.CancelledError):
                await started
            expected = "idle" if operation == "reset_motion" else "cancelled"
            assert host.status["state"] == expected
            assert not host.timeline.is_playing()
            for _ in range(3):
                await omni.kit.app.get_app().next_update_async()
            assert host.status["state"] == expected
            assert not host.motion_running
            if operation == "reset_motion":
                await host.execute("stop_motion", {})
                assert host.status["state"] == "idle"
                restarted = await host.execute("start_motion", lifecycle_plan())
                assert restarted["run_id"] != run_id
        finally:
            if not started.done():
                started.cancel()
            await asyncio.gather(started, return_exceptions=True)
            await host.close()
            session.close()


@pytest.mark.asyncio
async def test_check_reset_preserves_completed_report(tmp_path):
    host, session = await lifecycle_host(tmp_path)
    try:
        await host.execute("check_motion", lifecycle_plan())
        for _ in range(1500):
            await omni.kit.app.get_app().next_update_async()
            if host.status["state"] in {"succeeded", "failed"}:
                break
        assert host.status["state"] == "succeeded", host.status
        report = Path(host.status["reports"]["json"])
        original = report.read_bytes()
        await host.execute("stop_motion", {})
        assert host.status["state"] == "succeeded"
        assert report.read_bytes() == original
        await host.execute("reset_motion", {})
        await host.execute("stop_motion", {})
        assert host.status["state"] == "idle"
        assert report.read_bytes() == original
    finally:
        await host.close()
        session.close()
