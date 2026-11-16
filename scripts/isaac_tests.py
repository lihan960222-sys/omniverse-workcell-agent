import argparse
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import sys
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description="在 Isaac Sim 内运行真实运动、接触和资产检查。")
    parser.add_argument("--gui", action="store_true", help="显示 Isaac Sim 窗口")
    parser.add_argument("--timeout", type=float, default=900, help="测试执行超时秒数")
    args = parser.parse_args()
    sys.argv = [sys.argv[0]]
    if args.timeout <= 0:
        raise ValueError("timeout 必须大于零")
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"Isaac Sim 6.1 需要 Python 3.12，当前为 {sys.version}")
    repo = Path(__file__).resolve().parents[1]
    output = repo / ".work/isaac-tests" / uuid4().hex
    output.mkdir(parents=True)
    # 验收使用独立项目和令牌，端口已使用时立即报告。
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 8765))
    os.environ["WORKCELL_PROJECT_DIR"] = str(output / "project")
    os.environ["WORKCELL_TOKEN"] = secrets.token_urlsafe(32)
    os.environ["WORKCELL_WORKER_PYTHON"] = str(repo / ".venv/bin/python")
    os.environ["WORKCELL_URL"] = "http://127.0.0.1:8765"
    os.environ["WORKCELL_PORT"] = "8765"
    result_path = output / "result.json"
    result_path.write_text(json.dumps({"status": "starting", "passed": False}), encoding="utf-8")
    print(f"验收结果：{result_path}", flush=True)

    from isaacsim.simulation_app import SimulationApp

    # SimulationApp 必须先完成启动，随后才能导入 omni 模块。
    application = SimulationApp({
        "headless": not args.gui,
        "fast_shutdown": False,
        "extra_args": [
            "--ext-folder", str(repo / "extensions"), "--enable", "omni.kit.test",
            "--enable", "omni.kit.uiapp", "--enable", "omni.physx",
            "--enable", "omni.asset_validator.core", "--enable", "isaacsim.asset.validation",
            "--enable", "isaacsim.core.experimental.prims",
            "--enable", "isaacsim.core.simulation_manager",
            "--/exts/isaacsim.core.simulation_manager/default_engine=physx",
            "--/exts/isaacsim.physics.newton/auto_switch_on_startup=false",
        ],
    })
    exit_code = 1
    try:
        import aiohttp
        import omni.kit.app
        import omni.kit.test
        import omni.timeline
        import omni.usd
        from omni.kit.test.async_unittest import AsyncTextTestRunner

        manager = omni.kit.app.get_app().get_extension_manager()
        if manager.is_extension_enabled("workcell.agent"):
            raise RuntimeError("独立 IsaacHost 测试要求 workcell.agent 尚未启用")
        spec = importlib.util.spec_from_file_location("workcell_runtime_tests", repo / "tests/isaac/test_runtime.py")
        tests = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tests)

        class RuntimeTests(omni.kit.test.AsyncTestCase):
            async def setUp(self):
                self.workspace = output / self._testMethodName
                self.workspace.mkdir()

            async def tearDown(self):
                omni.timeline.get_timeline_interface().stop()
                await omni.kit.app.get_app().next_update_async()
                await omni.usd.get_context().close_stage_async()

            async def test_extension_bridge_health(self):
                await omni.usd.get_context().new_stage_async()
                self.assertTrue(manager.set_extension_enabled_immediate("workcell.agent", True))
                # 等待实际监听建立，Kit 继续处理 Extension 的异步启动。
                while True:
                    with socket.socket() as connection:
                        connection.settimeout(0.05)
                        if connection.connect_ex(("127.0.0.1", 8765)) == 0:
                            break
                    await omni.kit.app.get_app().next_update_async()
                headers = {"Authorization": f"Bearer {os.environ['WORKCELL_TOKEN']}"}
                async with aiohttp.ClientSession(headers=headers) as client:
                    async with client.get("http://127.0.0.1:8765/health") as response:
                        response.raise_for_status()
                        result = await response.json()
                        self.assertEqual(result["status"], "ready")
                        self.assertTrue(result["scene_revision"])

            async def test_real_joint_motion_and_stop(self):
                await tests.test_real_joint_motion_and_stop(self.workspace)

            async def test_official_validation_returns_rule_coverage(self):
                await tests.test_official_validation_returns_rule_coverage(self.workspace)

            async def test_contacts_are_real_events(self):
                await tests.test_contacts_are_real_events(self.workspace)

            async def test_contact_lifecycle_preserves_lost_events(self):
                await tests.test_contact_lifecycle_preserves_lost_events(self.workspace)

            async def test_start_during_running_preserves_motion(self):
                await tests.test_start_during_running_preserves_motion(self.workspace)

            async def test_initialization_cancellation(self):
                await tests.test_initialization_cancellation(self.workspace)

            async def test_check_reset_preserves_completed_report(self):
                await tests.test_check_reset_preserves_completed_report(self.workspace)

        suite = omni.kit.test.AsyncTestSuite()
        names = ("test_real_joint_motion_and_stop", "test_official_validation_returns_rule_coverage",
                 "test_contacts_are_real_events", "test_contact_lifecycle_preserves_lost_events",
                 "test_start_during_running_preserves_motion",
                 "test_initialization_cancellation", "test_check_reset_preserves_completed_report",
                 "test_extension_bridge_health")
        for name in names:
            suite.addTest(RuntimeTests(name))

        async def run_suite():
            return await asyncio.wait_for(AsyncTextTestRunner(verbosity=2, failfast=True).run(suite),
                                          timeout=args.timeout)

        result = application.run_coroutine(run_suite())
        passed = result.wasSuccessful() and result.testsRun == len(names) and not result.skipped
        report = {
            "status": "completed", "passed": passed, "tests_run": result.testsRun,
            "failures": [{"test": case.id(), "traceback": detail} for case, detail in result.failures],
            "errors": [{"test": case.id(), "traceback": detail} for case, detail in result.errors],
            "skipped": [{"test": case.id(), "reason": detail} for case, detail in result.skipped],
        }
        result_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        exit_code = 0 if passed else 1
    finally:
        application.close(exit_code=exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
