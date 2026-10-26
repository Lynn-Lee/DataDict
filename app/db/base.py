"""ORM 基类。

采集层与知识层的模型分别继承 `CollectionBase` / `KnowledgeBase`，
两者共用同一份 metadata（同一个库），但分开标注是为了让
`deploy/grants.sql` 的授权分层在代码里也可自动校验（DEV-TASKS T8.3）。
"""

from datetime import datetime

from sqlalchemy import MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 统一命名约定，避免 Alembic 自动生成的约束名在不同环境下不一致
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata_obj = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    metadata = metadata_obj


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


# ── 分层标记 ────────────────────────────────────────────────
# 用于 grants.sql 的一致性校验：新增模型必须显式归入某一层，
# 否则 T8.3 的授权测试会因表未登记而失败，从而拦住"新表漏授权"。

COLLECTION_TABLES: set[str] = set()
"""采集层：datadict_collector 可写。"""

KNOWLEDGE_TABLES: set[str] = set()
"""知识层：datadict_collector 只读。"""

SUPPORT_TABLES: set[str] = set()
"""支撑层：按表决定，见 deploy/grants.sql。"""
