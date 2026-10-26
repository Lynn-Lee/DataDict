"""应用配置。

设计要点（DEV-TASKS T0.3 验收标准）：
配置项全部有默认值或为必填，缺失时**启动即报错**，而不是运行到某个分支才炸。
Pydantic Settings 对必填字段的缺失会在实例化时抛 ValidationError，
而 `get_settings()` 在 `main.py` 的 lifespan 启动阶段就被调用，因此能在启动期暴露。
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, PostgresDsn, RedisDsn, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Env = Literal["local", "dev", "staging", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",  # 拼错的环境变量名会直接报错，而不是被静默忽略
    )

    # ── 应用 ──────────────────────────────────────────────
    APP_NAME: str = "metahub"
    ENV: Env = "local"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    # 前端构建产物目录。设置后由本服务同源托管静态资源（内网部署用）；留空则只提供 API。
    FRONTEND_DIST_DIR: str | None = None

    # ── 数据库 ────────────────────────────────────────────
    # PRD §M10-8 / DEV-TASKS T8.1：采集与 Web 必须使用不同的数据库角色。
    # 采集角色对知识层表只有 SELECT，由数据库强制，而非代码纪律。
    DB_URL_WEB: PostgresDsn
    DB_URL_COLLECTOR: PostgresDsn
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT: int = 30

    # ── Redis ────────────────────────────────────────────
    REDIS_URL: RedisDsn

    # ── 安全 ──────────────────────────────────────────────
    # 数据源连接凭证的 Fernet 主密钥。绝不落库，仅从环境变量注入。
    CREDENTIAL_SECRET_KEY: str = Field(min_length=32)
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_EXPIRE_MINUTES: int = 8 * 60

    # ── 采集 ──────────────────────────────────────────────
    SYNC_BATCH_SIZE: int = 1000  # PRD §6.4：大库分批提交
    SYNC_LOCK_TTL_SECONDS: int = 3600
    COLLECT_QUERY_TIMEOUT_SECONDS: int = 60  # 超时熔断，避免拖累生产库

    # ── 检索 ──────────────────────────────────────────────
    # 注意：pg_trgm 阈值是 **数据库级** 配置（ALTER DATABASE），不在这里设置。
    # 见 PRD §M8【v1.2 修正】与 DEV-TASKS T1.6——会话级 SET 在连接池下会漂移。
    SEARCH_MIN_QUERY_LENGTH: int = 2
    SEARCH_DEFAULT_PAGE_SIZE: int = 20
    SEARCH_MAX_PAGE_SIZE: int = 200

    @model_validator(mode="after")
    def _check_db_roles_differ(self) -> Self:
        """Web 与采集必须是不同的数据库角色。

        两者配成同一个账号时，PRD §M10-8 的物理隔离会被完全绕过，
        而且不会有任何报错——采集流程照样能写标注表，标注被覆盖时无从察觉。
        这是本项目最不该静默失败的一处配置，故在启动期硬校验。
        """
        web_user = self.DB_URL_WEB.hosts()[0].get("username")
        collector_user = self.DB_URL_COLLECTOR.hosts()[0].get("username")
        if web_user == collector_user:
            raise ValueError(
                f"DB_URL_WEB 与 DB_URL_COLLECTOR 使用了相同的数据库角色 "
                f"({web_user!r})，标注表的物理隔离将失效。"
                f"请按 deploy/grants.sql 创建 metahub_web 与 metahub_collector 两个角色。"
            )
        return self

    @property
    def is_prod(self) -> bool:
        return self.ENV == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # 必填字段由环境变量 / .env 填充；缺失时这里抛 ValidationError，
    # 而调用点在 lifespan 启动阶段，因此配置问题在启动期就暴露。
    return Settings()
