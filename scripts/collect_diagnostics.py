import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from workcell_agent.environment import check_environment


def runtime_environment() -> dict:
    url = os.environ.get("WORKCELL_URL", "http://127.0.0.1:8765")
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("WORKCELL_URL 必须是本机 HTTP 地址")
    token = os.environ["WORKCELL_TOKEN"]
    if len(token) < 16:
        raise ValueError("WORKCELL_TOKEN 至少需要 16 个字符")
    with httpx.Client(base_url=url, headers={"Authorization": f"Bearer {token}"},
                      timeout=15, trust_env=False) as client:
        submitted = client.post("/jobs", json={"operation": "environment"})
        submitted.raise_for_status()
        job_id = submitted.json()["job_id"]
        if not isinstance(job_id, str) or not job_id.isalnum():
            raise ValueError("Extension 返回的任务标识无效")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            response = client.get(f"/jobs/{job_id}")
            response.raise_for_status()
            record = response.json()
            if record["status"] == "succeeded":
                result = record["result"]
                if result["target"] != "isaac" or result["isaac_running"] is not True:
                    raise RuntimeError("返回的环境检查结果未确认 Isaac Sim 正在运行")
                return result
            if record["status"] not in {"queued", "running"}:
                raise RuntimeError("Extension 环境检查任务未成功完成")
            time.sleep(0.1)
    raise TimeoutError("Extension 环境检查超过 30 秒")


def collect_diagnostics(include_runtime: bool = False) -> Path:
    repository = Path(__file__).resolve().parents[1]
    core = check_environment("core")
    runtime = runtime_environment() if include_runtime else None
    core_tests = repository / ".work/core-tests.xml"
    isaac_tests = []
    for path in sorted((repository / ".work/isaac-tests").glob("*/result.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        # 诊断只保留测试状态和名称，详细日志继续保存在原始验收目录。
        isaac_tests.append({
            "path": str(path), "status": result["status"], "passed": result["passed"],
            "tests_run": result.get("tests_run"),
            "failed_tests": [entry["test"] for entry in result.get("failures", [])],
            "error_tests": [entry["test"] for entry in result.get("errors", [])],
            "skipped_tests": [entry["test"] for entry in result.get("skipped", [])],
        })
    report = {
        "schema_version": 1,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "core_environment": core,
        "runtime_requested": include_runtime,
        "runtime_environment": runtime,
        "tests": {"core": {"path": str(core_tests), "exists": core_tests.is_file()}, "isaac": isaac_tests},
    }
    directory = repository / ".work/diagnostics" / uuid4().hex
    directory.mkdir(parents=True)
    destination = directory / "report.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser(description="导出环境版本和已有测试结果的诊断 JSON。")
    parser.add_argument("--runtime", action="store_true", help="连接本机 Extension 并执行实际环境检查")
    args = parser.parse_args()
    destination = collect_diagnostics(args.runtime)
    print(destination)
    report = json.loads(destination.read_text(encoding="utf-8"))
    ready = report["core_environment"]["status"] == "ready"
    if args.runtime:
        ready = ready and report["runtime_environment"]["status"] == "ready"
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
