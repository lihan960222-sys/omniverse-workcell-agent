import asyncio
import hmac
import logging
from uuid import uuid4

from aiohttp import web
from pydantic import ValidationError

from .models import OperationRequest

logger = logging.getLogger(__name__)


class JobManager:
    def __init__(self, dispatcher):
        self.dispatcher = dispatcher
        self.jobs = {}
        self.requests = {}
        self.tasks = {}

    def submit(self, request: OperationRequest):
        data = request.model_dump(mode="json")
        if request.request_id in self.requests:
            previous, job_id = self.requests[request.request_id]
            if previous != data:
                raise ValueError("同一个 request_id 对应不同的请求")
            return self.jobs[job_id]
        job_id = uuid4().hex
        record = {"job_id": job_id, "request_id": request.request_id,
                  "operation": request.operation, "status": "queued", "result": None, "error": None}
        self.jobs[job_id] = record
        self.requests[request.request_id] = (data, job_id)
        self.tasks[job_id] = asyncio.create_task(self._run(request, record))
        return record

    async def _run(self, request, record):
        record["status"] = "running"
        try:
            record["result"] = await self.dispatcher.execute(request)
            record["status"] = "succeeded"
        except asyncio.CancelledError:
            record["status"] = "cancelled"
            raise
        except Exception as error:
            # 任务边界保留失败，客户端必须能够查询真实错误。
            logger.exception("操作失败: %s", request.operation)
            record["error"] = f"{type(error).__name__}: {error}"
            record["status"] = "failed"

    def cancel(self, job_id):
        record = self.jobs[job_id]
        if record["status"] in {"queued", "running"}:
            self.tasks[job_id].cancel()
            if record["status"] == "queued":
                record["status"] = "cancelled"
        return record

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


JOBS = web.AppKey("jobs", JobManager)


def create_app(dispatcher, token: str):
    if len(token) < 16:
        raise ValueError("会话令牌至少需要16个字符")

    @web.middleware
    async def authorize(request, handler):
        if not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {token}"):
            raise web.HTTPUnauthorized()
        if "Origin" in request.headers:
            raise web.HTTPForbidden(text="浏览器跨来源调用不受支持")
        return await handler(request)

    app = web.Application(middlewares=[authorize], client_max_size=2 * 1024 * 1024)
    jobs = JobManager(dispatcher)
    app[JOBS] = jobs

    async def health(request):
        return web.json_response({"status": "ready", "protocol": 1,
                                  "scene_revision": dispatcher.session.revision})

    async def submit(request):
        try:
            operation = OperationRequest.model_validate(await request.json())
        except (ValidationError, ValueError) as error:
            raise web.HTTPUnprocessableEntity(text=str(error)) from error
        try:
            record = jobs.submit(operation)
        except ValueError as error:
            raise web.HTTPConflict(text=str(error)) from error
        return web.json_response(record, status=202)

    async def get_job(request):
        job_id = request.match_info["job_id"]
        if job_id not in jobs.jobs:
            raise web.HTTPNotFound()
        return web.json_response(jobs.jobs[job_id])

    async def cancel(request):
        job_id = request.match_info["job_id"]
        if job_id not in jobs.jobs:
            raise web.HTTPNotFound()
        return web.json_response(jobs.cancel(job_id))

    async def cleanup(application):
        await jobs.close()

    app.router.add_get("/health", health)
    app.router.add_post("/jobs", submit)
    app.router.add_get("/jobs/{job_id}", get_job)
    app.router.add_post("/jobs/{job_id}/cancel", cancel)
    app.on_cleanup.append(cleanup)
    return app
