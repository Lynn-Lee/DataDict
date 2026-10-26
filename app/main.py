"""FastAPI 应用入口。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging
from app.db.session import close_pools, init_pools
from app.services.sync_scheduler import MetadataSyncScheduler


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # get_settings() 放在最前：配置缺失或非法时在这里就抛，不会带病启动
    settings = get_settings()
    setup_logging(settings)
    logger.info("启动 {} env={} debug={}", settings.APP_NAME, settings.ENV, settings.DEBUG)

    sync_scheduler: MetadataSyncScheduler | None = None
    init_pools(settings)
    try:
        sync_scheduler = MetadataSyncScheduler()
        await sync_scheduler.start()
        yield
    finally:
        if sync_scheduler is not None:
            sync_scheduler.shutdown()
        await close_pools()
        logger.info("已停止 {}", settings.APP_NAME)


def mount_frontend(app: FastAPI, dist_dir: Path, api_prefix: str) -> None:
    """同源托管前端构建产物，未命中的前端路由回落到 index.html（SPA）。"""
    index_html = dist_dir / "index.html"
    assets_dir = dist_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    # 普通 def：FastAPI 放进线程池执行，文件系统检查不会阻塞事件循环
    @app.get("/{path:path}", include_in_schema=False)
    def spa_fallback(path: str) -> FileResponse:
        # 未知的 API 路径必须是 404，而不是一个 200 的 HTML 页面
        if path.startswith(api_prefix.lstrip("/")):
            raise HTTPException(status_code=404)
        candidate = (dist_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist_dir.resolve()):
            return FileResponse(candidate)
        return FileResponse(index_html)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="DataDict 元数据知识库",
        description="数据库元数据知识库 —— 表/字段元数据采集与业务语义标注平台",
        version="0.1.0",
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    if settings.FRONTEND_DIST_DIR:
        dist_dir = Path(settings.FRONTEND_DIST_DIR)
        if not (dist_dir / "index.html").is_file():
            raise RuntimeError(f"FRONTEND_DIST_DIR 下找不到 index.html: {dist_dir}")
        mount_frontend(app, dist_dir, settings.API_V1_PREFIX)
    return app


app = create_app()
