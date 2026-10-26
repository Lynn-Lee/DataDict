"""支撑层模型（DEV-TASKS T1.3）。"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.sql import text

from app.db.base import SUPPORT_TABLES, Base


class SchemaChangeLog(Base):
    __tablename__ = "schema_change_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    urn: Mapped[str] = mapped_column(String(768), nullable=False)
    table_urn: Mapped[str | None] = mapped_column(String(512))
    asset_type: Mapped[str | None] = mapped_column(String(16))
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    before_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    rename_candidate: Mapped[str | None] = mapped_column(String(768))
    rename_status: Mapped[str | None] = mapped_column(String(16))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_change_time", "detected_at"),
        Index("idx_change_table", "table_urn"),
    )


class SyncJobLog(Base):
    __tablename__ = "sync_job_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    trigger_type: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str | None] = mapped_column(String(16))
    scanned_tables: Mapped[int] = mapped_column(Integer, default=0)
    changed_count: Mapped[int] = mapped_column(Integer, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    comment_fill_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    error_msg: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)


class SyncFailDetail(Base):
    __tablename__ = "sync_fail_detail"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("sync_job_log.id"), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    db_name: Mapped[str | None] = mapped_column(String(128))
    table_name: Mapped[str | None] = mapped_column(String(128))
    stage: Mapped[str | None] = mapped_column(String(32))
    error_type: Mapped[str | None] = mapped_column(String(64))
    error_msg: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_fail_job", "job_id", "resolved"),)


class ViewLog(Base):
    __tablename__ = "view_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    urn: Mapped[str] = mapped_column(String(768), nullable=False)
    asset_type: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_view_urn", "urn", "created_at"),
        Index("idx_view_user", "user_id", "created_at"),
    )


class SearchLog(Base):
    __tablename__ = "search_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    keyword: Mapped[str | None] = mapped_column(String(255))
    result_cnt: Mapped[int | None] = mapped_column(Integer)
    search_type: Mapped[str] = mapped_column(String(16), default="KEYWORD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_search_kw", "keyword", "created_at"),)


class SearchClick(Base):
    __tablename__ = "search_click"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("search_log.id"), nullable=False)
    urn: Mapped[str] = mapped_column(String(768), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_click_search", "search_id"),)


class AnnotationTodo(Base):
    __tablename__ = "annotation_todo"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    urn: Mapped[str] = mapped_column(String(768), nullable=False)
    todo_type: Mapped[str] = mapped_column(String(32), nullable=False)
    domain_id: Mapped[int | None] = mapped_column(BigInteger)
    assignee_id: Mapped[int | None] = mapped_column(BigInteger)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # server_default 与迁移对齐：缺失时 SQLAlchemy 会对未赋值列显式插 NULL，
    # 数据库的 DEFAULT now() 不会生效（治理待办产生时间曾因此为空）。
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_todo_open",
            "urn",
            "todo_type",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
        Index("idx_todo_assignee", "assignee_id", "status"),
        Index("idx_todo_domain", "domain_id", "status"),
    )


class SysUser(Base):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    real_name: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(128))
    # V0.1 简单登录的本地密码哈希（pbkdf2）。SSO/LDAP 用户此列为空，见 DEV-TASKS T8.4。
    password_hash: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserRole(Base):
    __tablename__ = "user_role"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    domain_id: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (UniqueConstraint("user_id", "role", "domain_id", name="uq_user_role_scope"),)


class ApiKey(Base):
    __tablename__ = "api_key"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key_name: Mapped[str] = mapped_column(String(128), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    rate_limit: Mapped[int] = mapped_column(Integer, default=1000)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserFavorite(Base):
    __tablename__ = "user_favorite"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    urn: Mapped[str] = mapped_column(String(768), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("user_id", "urn", name="uq_user_favorite_user_id_urn"),)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    urn: Mapped[str] = mapped_column(String(768), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    reporter_id: Mapped[int | None] = mapped_column(BigInteger)
    handler_id: Mapped[int | None] = mapped_column(BigInteger)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


SUPPORT_TABLES.update(
    {
        "schema_change_log",
        "sync_job_log",
        "sync_fail_detail",
        "view_log",
        "search_log",
        "search_click",
        "annotation_todo",
        "sys_user",
        "user_role",
        "api_key",
        "user_favorite",
        "feedback",
    }
)
