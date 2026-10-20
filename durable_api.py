"""Same-origin local UI + durable task API. No model work inside POST handlers."""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from task_service import TaskService

SOURCE_ROOT = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("BARIS_WORKSPACE", SOURCE_ROOT)).resolve()
BUILD = "local-ui-v5"


@asynccontextmanager
async def lifespan(app):
    service = TaskService(WORKSPACE)
    app.state.service = service
    await service.start()
    try:
        yield
    finally:
        await service.close()


app = FastAPI(title="Barış AI", lifespan=lifespan)


def service(request: Request):
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "Başka kaynaktan işlem isteği reddedildi.")
    return request.app.state.service


class TaskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=30000)
    expected_files: dict[str, str] | None = None
    budget_seconds: int = Field(default=900, ge=30, le=1800)


def enqueue(req, request, engine):
    if not req.message.strip():
        raise HTTPException(422, "Görev boş olamaz.")
    if req.expected_files is not None and (
        not req.expected_files or len(req.expected_files) > 100
        or sum(len(v) for v in req.expected_files.values()) > 30000
    ):
        raise HTTPException(422, "Dosya kabul koşulları boyut sınırını aşıyor.")
    payload = req.model_dump()
    payload["workspace"] = str(WORKSPACE)
    key = request.headers.get("idempotency-key") or uuid.uuid4().hex
    if len(key) > 100:
        raise HTTPException(422, "İşlem anahtarı çok uzun.")
    try:
        task_id = engine.store.submit(payload, key)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except OverflowError as exc:
        raise HTTPException(429, str(exc))
    return task_id


@app.get("/")
async def index():
    return FileResponse(SOURCE_ROOT / "public/index.html", headers={"Cache-Control": "no-store"})


@app.get("/app.js")
async def script():
    return FileResponse(SOURCE_ROOT / "public/app.js", media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})


@app.get("/api/engine_info")
async def info(engine=Depends(service)):
    with engine.store.connection() as db:
        busy = db.execute("SELECT 1 FROM jobs WHERE status='RUNNING'").fetchone() is not None
    return {"engine_protocol": "baris-execution-v2", "build": BUILD, "tool_loop": True,
            "durable_tasks": True, "busy": busy, "source_root": str(SOURCE_ROOT),
            "workspace": str(WORKSPACE), "instance": os.environ.get("BARIS_INSTANCE", ""),
            "release": os.environ.get("BARIS_RELEASE", "")}


@app.post("/api/tasks", status_code=202)
async def submit(req: TaskRequest, request: Request, engine=Depends(service)):
    task_id = enqueue(req, request, engine)
    return {"task_id": task_id, "status_url": "/api/tasks/" + task_id}


@app.get("/api/tasks/{task_id}")
async def status(task_id: str, after: int = 0, engine=Depends(service)):
    try:
        return engine.store.public(task_id, max(0, after))
    except KeyError:
        raise HTTPException(404, "Görev bulunamadı.")


@app.post("/api/tasks/{task_id}/cancel", status_code=202)
async def cancel(task_id: str, engine=Depends(service)):
    try:
        engine.store.request_cancel(task_id)
    except KeyError:
        raise HTTPException(404, "Görev bulunamadı.")
    return {"task_id": task_id, "message": "Durdurma isteği kaydedildi."}


@app.post("/api/chat")
async def compatible_chat(req: TaskRequest, request: Request, engine=Depends(service)):
    task_id = enqueue(req, request, engine)
    # Existing curl clients get a result quickly or a durable job handle, never a lost job.
    for _ in range(50):
        job = engine.store.public(task_id)
        if job["result"]:
            return job["result"]
        await asyncio.sleep(0.1)
    return JSONResponse(status_code=202, content={
        "task_id": task_id, "status": "QUEUED_OR_RUNNING",
        "status_url": "/api/tasks/" + task_id,
        "verified": False, "reply": "Görev arka planda çalışıyor; durum bağlantısından izleyin."})
