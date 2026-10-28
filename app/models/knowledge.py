"""知识层元数据模型（DEV-TASKS T1.2）。

这些表承载人工维护的业务语义，采集角色只能只读，不能覆盖。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import UniqueConstraint

from app.db.base import KNOWLEDGE_TABLES, Base


class BusinessDomain(Base):
    __tablename__ = "business_domain"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("business_domain.id"))
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None]
    owner_id: Mapped[int | None] = mapped_column(BigInteger)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DomainRule(Base):
    __tablename__ = "domain_rule"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    domain_id: Mapped[int] = mapped_column(ForeignKey("business_domain.id"), nullable=False)
    source_id: Mapped[int | None] = mapped_column(BigInteger)
    db_pattern: Mapped[str | None] = mapped_column(String(128))
    table_pattern: Mapped[str | None] = mapped_column(String(128))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None]
    color: Mapped[str | None] = mapped_column(String(16))
    exclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (UniqueConstraint("category", "code", name="uq_tag_category_code"),)


class Dictionary(Base):
    __tablename__ = "dict"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), default="MANUAL")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssetAnnotation(Base):
    __tablename__ = "asset_annotation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    urn: Mapped[str] = mapped_column(String(768), unique=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    domain_id: Mapped[int | None] = mapped_column(ForeignKey("business_domain.id"))
    business_meaning: Mapped[str | None]
    logical_type_override: Mapped[str | None] = mapped_column(String(32))
    dict_id: Mapped[int | None] = mapped_column(ForeignKey("dict.id"))
    dict_inline: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    sample_value: Mapped[str | None]
    source_desc: Mapped[str | None]
    usage_note: Mapped[str | None]
    owner_id: Mapped[int | None] = mapped_column(BigInteger)
    lifecycle: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    status: Mapped[str] = mapped_column(String(16), default="CONFIRMED")
    source_type: Mapped[str] = mapped_column(String(16), default="MANUAL")
    inherited_from: Mapped[str | None] = mapped_column(String(768))
    search_text: Mapped[str] = mapped_column(
        Computed(
            "coalesce(business_meaning,'') || ' ' || "
            "coalesce(usage_note,'') || ' ' || "
            "coalesce(source_desc,'')",
            persisted=True,
        )
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_annotation_domain", "domain_id"),
        Index("idx_annotation_status", "status", "source_type"),
    )


class AssetTagRel(Base):
    __tablename__ = "asset_tag_rel"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    urn: Mapped[str] = mapped_column(String(768), nullable=False)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), nullable=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("urn", "tag_id", name="uq_asset_tag_rel_urn_tag_id"),
        Index("idx_asset_tag_tag", "tag_id"),
    )


class AnnotationHistory(Base):
    __tablename__ = "annotation_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    urn: Mapped[str] = mapped_column(String(768), nullable=False)
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    operator_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_anno_hist_urn", "urn", "created_at"),)


class CommonColumnBlacklist(Base):
    __tablename__ = "common_column_blacklist"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    column_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    reason: Mapped[str | None]
    is_whitelist: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StandardField(Base):
    """标准字段定义（字段统一治理的核心实体，也是业务含义的唯一真相源）。

    生命周期：CLUSTER/IMPORT/MANUAL 生成 DRAFT 候选 → 人工确认 CONFIRMED →
    废弃 DEPRECATED；若确认时发现标准库已有同义标准，则本候选 MERGED 进目标
    标准（存量字段迁到目标下，原字段名记为目标的业务别名），不产生第二个标准。

    has_conflict 表示组内类型冲突，必须人工裁决后才能定版。
    cluster_key 是候选来源字段名——标准可被改名，聚类按 cluster_key 匹配，
    避免改名后重新聚类又产出同一批字段的重复候选。
    """

    __tablename__ = "standard_field"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    standard_name: Mapped[str] = mapped_column(String(128), nullable=False)
    cluster_key: Mapped[str | None] = mapped_column(String(128))
    # 通用字段名同名不同义时按释义分组，sub_key 存该组释义哈希；'' 表示按字段名整体定标
    sub_key: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    merged_into_id: Mapped[int | None] = mapped_column(ForeignKey("standard_field.id"))
    business_meaning: Mapped[str | None]
    logical_type: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_type: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    source_type: Mapped[str] = mapped_column(String(16), default="CLUSTER")
    has_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    type_distribution: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    # Excel 文档来源出现次数（candidate_count 为源库同步出现次数，两路并集产候选）
    doc_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "uq_standard_field_active_name_sub",
            "standard_name",
            "sub_key",
            unique=True,
            postgresql_where=text("status IN ('DRAFT', 'CONFIRMED')"),
        ),
        Index("idx_standard_field_status", "status"),
        Index("idx_standard_field_cluster_sub", "cluster_key", "sub_key"),
    )


class StandardFieldItem(Base):
    """标准字段定义与存量源字段的关联，定版后回算 conforms 供治理度量。"""

    __tablename__ = "standard_field_item"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    standard_field_id: Mapped[int] = mapped_column(ForeignKey("standard_field.id"), nullable=False)
    column_urn: Mapped[str] = mapped_column(String(768), nullable=False)
    conforms: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("standard_field_id", "column_urn", name="uq_standard_field_item"),
        Index("idx_standard_field_item_urn", "column_urn"),
    )


class ExcelFieldDoc(Base):
    """Excel 历史数据字典的字段文档留档（标准定义库的输入来源之一）。

    与源库同步的 column_meta 平级：候选标准定义按字段名取两路的并集，
    只在 Excel 出现、或只在源库出现的字段名同样产出候选。
    按 source_file 幂等——同一文件重复上传先清旧记录再写入。
    """

    __tablename__ = "excel_field_doc"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_file: Mapped[str] = mapped_column(String(255), nullable=False)
    sheet_name: Mapped[str | None] = mapped_column(String(128))
    table_name: Mapped[str] = mapped_column(String(128), nullable=False)
    table_desc: Mapped[str | None]
    column_name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_desc: Mapped[str | None]
    column_type: Mapped[str | None] = mapped_column(String(128))
    remark: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_excel_doc_column", "column_name"),
        Index("idx_excel_doc_table", "table_name", "column_name"),
        Index("idx_excel_doc_file", "source_file"),
    )


KNOWLEDGE_TABLES.update(
    {
        "business_domain",
        "domain_rule",
        "tag",
        "dict",
        "asset_annotation",
        "asset_tag_rel",
        "annotation_history",
        "common_column_blacklist",
        "standard_field",
        "standard_field_item",
        "excel_field_doc",
    }
)
