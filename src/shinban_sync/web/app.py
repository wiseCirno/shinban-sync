import asyncio
import os
import subprocess
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir
from typing import IO, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.responses import Response

from shinban_sync.core.catalog import (
    discover_groups,
    search_tv,
    series_detail,
    subscription_from_discovery,
    subtitle_names,
)
from shinban_sync.core.config import ConfigError, ConfigManager
from shinban_sync.core.schedule import (
    ScheduleError,
    describe_schedule,
    install_system_cron,
    sync_argv,
)
from shinban_sync.utils.logger import logger
from shinban_sync.utils.runlog import list_logs, plain_log, read_log


class AnimeBody(BaseModel):
    search_keyword: str
    filename: str
    subtitle: str
    season_air_date: str
    first_air_date: str | None = None
    season: int = 1
    episode_count: int = 12
    language: str = "chs"


class SubscribeBody(BaseModel):
    series_id: int
    season_number: int
    subtitle: str


class ScheduleBody(BaseModel):
    mode: str = "daily"
    hour: int = 4
    minute: int = 0
    interval_hours: int = 12
    weekday: int = 1
    enabled: bool = False
    install: bool = False


class SettingsBody(BaseModel):
    telegram_bot_token: str | None = None
    telegram_user_id: str | int | None = None
    tmdb_token: str | None = None
    downloader: dict[str, Any] | None = None
    storage: dict[str, Any] | None = None
    web: dict[str, Any] | None = None


class JobBook:
    def __init__(self):
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def start(self, config_path: str) -> dict[str, Any]:
        async with self._lock:
            if any(job["status"] == "running" for job in self.jobs.values()):
                raise HTTPException(status_code = 409, detail = "已有同步任务在运行")
            job_id = uuid.uuid4().hex[:12]
            log_path = Path(gettempdir()) / "shinban-sync" / f"{job_id}.log"
            log_path.parent.mkdir(parents = True, exist_ok = True)
            handle = log_path.open("w", encoding = "utf-8")
            process = await asyncio.create_subprocess_exec(
                *sync_argv(config_path),
                stdout = handle,
                stderr = asyncio.subprocess.STDOUT,
            )
            self.jobs[job_id] = {
                "status": "running",
                "return_code": None,
                "log_path": log_path,
                "handle": handle,
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            asyncio.create_task(self._watch(job_id, process, handle))
            return {"id": job_id, "status": "running"}

    async def _watch(
            self, job_id: str, process: asyncio.subprocess.Process, handle: IO[str]
    ) -> None:
        code = await process.wait()
        handle.close()
        job = self.jobs.get(job_id)
        if job is None:
            return
        job["return_code"] = code
        job["status"] = "finished"

    def view(self, job_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(job_id)
        if job is None:
            return None
        log = ""
        path: Path = job["log_path"]
        if path.exists():
            log = plain_log(path.read_text(encoding = "utf-8", errors = "replace"))[-20000:]
        return {
            "id": job_id,
            "status": job["status"],
            "return_code": job["return_code"],
            "started_at": job.get("started_at"),
            "log": log,
        }

    def current(self) -> dict[str, Any] | None:
        for job_id, job in self.jobs.items():
            if job["status"] == "running":
                return self.view(job_id)
        return None


def create_app(config_path: str) -> FastAPI:
    app = FastAPI(title = "Shinban Sync", docs_url = None, redoc_url = None)
    app.state.config_path = config_path
    app.state.jobs = JobBook()

    @app.middleware("http")
    async def authorize(request: Request, call_next: Callable[[Request], Awaitable[Response]]):
        path = request.url.path
        if path.startswith("/api/") and path != "/api/health":
            try:
                manager = ConfigManager(request.app.state.config_path)
                expected = manager.get_web_settings().get("token") or ""
            except ConfigError as exc:
                return _error(exc)
            provided = request.headers.get("x-shinban-token", "")
            if expected and provided != expected:
                return JSONResponse(status_code = 401, content = {"detail": "需要 Web 令牌"})
        return await call_next(request)

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/")
    async def index():
        frontend = _frontend_dir()
        if frontend is None:
            raise HTTPException(status_code = 503, detail = "网页还没有构建")
        return FileResponse(frontend / "index.html")

    @app.get("/api/settings")
    async def get_settings(request: Request):
        return _manager(request).public_view()

    @app.put("/api/settings")
    async def put_settings(request: Request, body: SettingsBody):
        manager = _manager(request)
        try:
            manager.apply_settings(body.model_dump())
        except (ConfigError, ValueError) as exc:
            raise HTTPException(status_code = 400, detail = str(exc)) from exc
        return manager.public_view()

    @app.get("/api/anime")
    async def list_anime(request: Request):
        return {"anime": _manager(request).public_view()["anime"], "subtitles": subtitle_names()}

    @app.post("/api/anime")
    async def add_anime(request: Request, body: AnimeBody):
        manager = _manager(request)
        try:
            created = manager.add_anime_config(body.model_dump())
        except (ConfigError, KeyError, ValueError) as exc:
            raise HTTPException(status_code = 400, detail = str(exc)) from exc
        if not created:
            raise HTTPException(status_code = 409, detail = "同一文件名和季数的订阅已存在")
        return {"ok": True}

    @app.delete("/api/anime")
    async def delete_anime(request: Request, filename: str, season: int = 1):
        if not _manager(request).remove_anime_config(filename, season):
            raise HTTPException(status_code = 404, detail = "订阅不存在")
        return {"ok": True}

    @app.get("/api/search")
    async def search(request: Request, q: str = ""):
        query = q.strip()
        if not query:
            raise HTTPException(status_code = 400, detail = "缺少搜索关键字")
        try:
            return {"results": await search_tv(_manager(request).get_tmdb_token(), query)}
        except ConfigError as exc:
            raise HTTPException(status_code = 400, detail = str(exc)) from exc

    @app.get("/api/series/{series_id}")
    async def series(request: Request, series_id: int):
        try:
            detail = await series_detail(_manager(request).get_tmdb_token(), series_id)
        except ConfigError as exc:
            raise HTTPException(status_code = 400, detail = str(exc)) from exc
        if detail is None:
            raise HTTPException(status_code = 404, detail = "没有找到这部剧")
        return detail

    @app.get("/api/series/{series_id}/seasons/{season_number}/groups")
    async def groups(request: Request, series_id: int, season_number: int):
        try:
            return await discover_groups(
                _manager(request).get_tmdb_token(), series_id, season_number
            )
        except ConfigError as exc:
            raise HTTPException(status_code = 400, detail = str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code = 404, detail = str(exc)) from exc

    @app.post("/api/subscriptions")
    async def subscribe(request: Request, body: SubscribeBody):
        manager = _manager(request)
        try:
            discovered = await discover_groups(
                manager.get_tmdb_token(), body.series_id, body.season_number
            )
            anime = subscription_from_discovery(discovered, body.subtitle)
            created = manager.add_anime_config(anime)
        except ConfigError as exc:
            raise HTTPException(status_code = 400, detail = str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code = 404, detail = str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code = 400, detail = str(exc)) from exc
        if not created:
            raise HTTPException(status_code = 409, detail = "同一文件名和季数的订阅已存在")
        return {"ok": True, "anime": anime}

    @app.post("/api/sync")
    async def start_sync(request: Request):
        return await request.app.state.jobs.start(str(_manager(request).config_path))

    @app.get("/api/jobs/current")
    async def current_job(request: Request):
        return request.app.state.jobs.current() or {"id": None, "status": "idle", "log": ""}

    @app.get("/api/jobs/{job_id}")
    async def job(request: Request, job_id: str):
        found = request.app.state.jobs.view(job_id)
        if found is None:
            raise HTTPException(status_code = 404, detail = "任务不存在")
        return found

    @app.get("/api/schedule")
    async def get_schedule(request: Request):
        manager = _manager(request)
        schedule = manager.get_schedule()
        return {**schedule, **describe_schedule(schedule["cron"], str(manager.config_path))}

    @app.put("/api/schedule")
    async def put_schedule(request: Request, body: ScheduleBody):
        manager = _manager(request)
        try:
            manager.set_schedule(body.model_dump(exclude = {"install"}))
            schedule = manager.get_schedule()
            described = describe_schedule(schedule["cron"], str(manager.config_path))
            installed = False
            if body.install:
                install_system_cron(schedule["cron"], str(manager.config_path))
                installed = True
        except (ConfigError, ScheduleError, OSError) as exc:
            raise HTTPException(status_code = 400, detail = str(exc)) from exc
        return {**schedule, **described, "installed": installed}

    @app.get("/api/logs")
    async def logs(request: Request):
        return {"logs": list_logs(_manager(request).config_path)}

    @app.get("/api/logs/{name}")
    async def log_file(request: Request, name: str):
        try:
            text = read_log(_manager(request).config_path, name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code = 404, detail = "日志不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code = 400, detail = str(exc)) from exc
        return {"name": name, "text": text}

    frontend = _frontend_dir()
    if frontend is not None:

        @app.get("/{full_path:path}", include_in_schema = False)
        async def frontend_files(full_path: str):
            if full_path == "api" or full_path.startswith("api/"):
                raise HTTPException(status_code = 404, detail = "Not Found")
            root = frontend.resolve()
            candidate = (frontend / full_path).resolve()
            if candidate != root and root not in candidate.parents:
                raise HTTPException(status_code = 404, detail = "Not Found")
            if candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(root / "index.html")

    return app


def _frontend_dir() -> Path | None:
    override = os.getenv("SHINBAN_WEB_DIST")
    candidates = []
    if override:
        candidates.append(Path(override))
    candidates.append(Path(__file__).resolve().parents[3] / "web" / ".output" / "public")
    for path in candidates:
        if (path / "index.html").is_file():
            return path
    return None


def ensure_frontend() -> None:
    """没有构建结果时，在项目里构建一次。之后 `shinban-sync web` 单独即可打开界面。"""
    if _frontend_dir() is not None:
        return
    web_dir = Path(__file__).resolve().parents[3] / "web"
    if not (web_dir / "package.json").is_file():
        raise ConfigError("没有找到网页。请在项目根目录启动，或使用已经带好界面的 Docker 镜像。")
    logger.info("正在准备网页，第一次会安装依赖并构建")
    try:
        subprocess.run(["pnpm", "install"], cwd = web_dir, check = True)
        subprocess.run(["pnpm", "generate"], cwd = web_dir, check = True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ConfigError(f"构建网页失败：{exc}。请确认已安装 pnpm。") from exc
    if _frontend_dir() is None:
        raise ConfigError("网页构建结束，但没有找到 web/.output/public")


def _manager(request: Request) -> ConfigManager:
    try:
        return ConfigManager(request.app.state.config_path)
    except ConfigError as exc:
        raise HTTPException(status_code = 400, detail = str(exc)) from exc


def _error(exc: ConfigError):
    return JSONResponse(status_code = 400, content = {"detail": str(exc)})
