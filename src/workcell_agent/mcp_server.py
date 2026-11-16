import os
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP

from .models import Operation, OperationRequest

server = FastMCP("omniverse-workcell-agent", instructions=(
    "先读取 environment 和 inspect_scene。场景修改需要最新 scene_revision。"
    "submit_operation 返回任务标识，必须用 get_job 查询实际结果。"
    "只有 succeeded 表示该任务成功；未执行的检查不能报告通过。"
    "start_motion/check_motion 的任务成功表示启动完成；必须继续查询 motion_status 中同一 run_id 的实际状态。"
    "STEP 工作流：usd_brep_status、必要时 install_usd_brep，再 import_step，随后 set_material。"
    "安装任务可能需要构建官方转换器，必须查询完成状态。source 为 Linux 本地 STP 路径。"))


async def call_bridge(method, path, payload=None):
    url = os.environ.get("WORKCELL_URL", "http://127.0.0.1:8765")
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("WORKCELL_URL 必须是本机 HTTP 地址")
    token = os.environ["WORKCELL_TOKEN"]
    async with httpx.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {token}"},
                                 timeout=15, trust_env=False) as client:
        response = await client.request(method, path, json=payload)
        response.raise_for_status()
        return response.json()


@server.tool(description="查询 Isaac Sim Extension 连接状态和场景版本。")
async def connection_status() -> dict:
    return await call_bridge("GET", "/health")


@server.tool(description="执行工站操作，返回 job_id。parameters 必须符合对应操作的数据格式；完成后查询 get_job。")
async def submit_operation(operation: Operation, parameters: dict | None = None,
                           scene_revision: str | None = None, request_id: str | None = None) -> dict:
    fields = {"operation": operation, "parameters": parameters or {}, "scene_revision": scene_revision}
    if request_id:
        fields["request_id"] = request_id
    request = OperationRequest.model_validate(fields)
    return await call_bridge("POST", "/jobs", request.model_dump(mode="json"))


@server.tool(description="读取任务状态、实际结果或错误。")
async def get_job(job_id: str) -> dict:
    if not job_id.isalnum():
        raise ValueError("非法任务标识")
    return await call_bridge("GET", f"/jobs/{job_id}")


@server.tool(description="取消转换或检查任务。已提交的场景修改继续保留；运动通过 stop_motion 终止。")
async def cancel_job(job_id: str) -> dict:
    if not job_id.isalnum():
        raise ValueError("非法任务标识")
    return await call_bridge("POST", f"/jobs/{job_id}/cancel")


@server.tool(description="获取七项功能的参数定义，配置操作前读取。")
def operation_schema(operation: str) -> dict:
    from .models import MaterialSpec, PhysicsSpec, JointSpec, StepImportSpec
    from .motion import MotionPlan
    models = {"set_material": MaterialSpec, "set_physics": PhysicsSpec,
              "create_joint": JointSpec, "start_motion": MotionPlan, "check_motion": MotionPlan,
              "import_step": StepImportSpec}
    if operation in models:
        return models[operation].model_json_schema()
    schemas = {
        "convert_step": {"source": "Linux STP absolute path"},
        "convert_step_brep": {"source": "Linux STP absolute path"},
        "usd_brep_status": {}, "install_usd_brep": {},
        "import_asset": {"path": "USD absolute path", "prim_path": "/World/Imported", "source_prim": "optional source Prim"},
        "query_features": {"manifest": "geometry manifest path", "prim_path": "current part prim path",
                           "asset_root": "/World/Imported"},
        "check_interference": {"manifest": "geometry manifest path", "length_tolerance_m": 1e-6,
                               "volume_tolerance_m3": 1e-12, "asset_root": "/World/Imported"},
        "validation_rules": {},
        "validate_asset": {"categories": "optional list from validation_rules; omitted uses enabled categories and rules"},
        "inspect_scene": {}, "get_selection": {}, "save_project": {}, "environment": {},
        "motion_status": {}, "pause_motion": {}, "resume_motion": {}, "stop_motion": {}, "reset_motion": {},
    }
    if operation not in schemas:
        raise ValueError("未知操作")
    return schemas[operation]


def main():
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
