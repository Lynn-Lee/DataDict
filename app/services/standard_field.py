"""标准字段定义：同名聚类候选生成（字段统一治理 T-S2）。

治理路径：存量字段原样同步 → 按字段名聚类产出候选标准定义（零标注成本）→
人工确认定版 → 对外提供设计态查询。同名字段在多数系统中本来就叫法一致，
字段名即最强的语义先验；同名不同型自动标记冲突，强制人工裁决。
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, DataDictError, NotFoundError
from app.models.knowledge import (
    AssetTagRel,
    CommonColumnBlacklist,
    StandardField,
    StandardFieldItem,
    Tag,
)
from app.models.metadata import ColumnMeta, TableMeta
from app.schemas.standard_fields import (
    ConfirmStandardFieldPayload,
    StandardFieldDetailOut,
    StandardFieldItemOut,
    StandardFieldLibraryOut,
    StandardFieldOut,
    StandardFieldTagOut,
)

# 业务标签：同一标准释义在不同业务域的叫法（别名）。复用 PRD M5 标签体系，
# 标准定义不是 URN 资产，用 standard:{id} 约定接入 asset_tag_rel。
STANDARD_TAG_CATEGORY = "业务别名"


def _standard_tag_urn(standard_id: int) -> str:
    return f"standard:{standard_id}"


@dataclass
class ClusterCandidate:
    """单个字段名聚合出的候选标准定义。"""

    column_name: str
    candidate_count: int
    type_distribution: dict[str, int]
    recommended_logical_type: str | None
    recommended_raw_type: str | None
    has_conflict: bool
    suggested_meaning: str | None
    column_urns: list[str] = field(default_factory=list)


@dataclass
class ClusteringSummary:
    generated: int = 0
    updated: int = 0
    skipped_confirmed: int = 0
    skipped_conflict: int = 0


def build_name_clusters(
    rows: Iterable[tuple[str, str, str, str | None, str | None]],
    *,
    excluded_names: set[str] | None = None,
) -> list[ClusterCandidate]:
    """把 (column_name, urn, raw_type, logical_type, raw_comment) 行聚成候选组。

    推荐规则：类型取组内众数；逻辑类型不一致 → has_conflict 强制人工裁决；
    中文释义取组内最高频的非空原始注释，仅作确认时的预填。
    """
    excluded = excluded_names or set()
    grouped: dict[str, list[tuple[str, str, str | None, str | None]]] = {}
    for column_name, urn, raw_type, logical_type, raw_comment in rows:
        if column_name in excluded:
            continue
        grouped.setdefault(column_name, []).append((urn, raw_type, logical_type, raw_comment))

    candidates: list[ClusterCandidate] = []
    for column_name, members in grouped.items():
        type_counter = Counter(raw_type for _, raw_type, _, _ in members)
        logical_counter = Counter(logical for _, _, logical, _ in members)
        meaning_counter = Counter(
            comment.strip() for _, _, _, comment in members if comment and comment.strip()
        )
        has_conflict = len(logical_counter) > 1
        top_raw, _ = type_counter.most_common(1)[0]
        top_logical = logical_counter.most_common(1)[0][0]
        candidates.append(
            ClusterCandidate(
                column_name=column_name,
                candidate_count=len(members),
                type_distribution=dict(sorted(type_counter.items(), key=lambda kv: -kv[1])),
                recommended_logical_type=top_logical,
                recommended_raw_type=top_raw,
                has_conflict=has_conflict,
                suggested_meaning=meaning_counter.most_common(1)[0][0] if meaning_counter else None,
                column_urns=[urn for urn, _, _, _ in members],
            )
        )
    candidates.sort(key=lambda c: -c.candidate_count)
    return candidates


async def load_cluster_rows(session: AsyncSession) -> list[tuple[str, str, str, str, str | None]]:
    """读取未删除字段的聚类输入行，排除黑名单字段名。"""
    blacklist_rows = await session.execute(
        select(CommonColumnBlacklist.column_name).where(
            CommonColumnBlacklist.is_whitelist.is_(False)
        )
    )
    excluded_names = {name for (name,) in blacklist_rows}

    rows = await session.execute(
        select(
            ColumnMeta.column_name,
            ColumnMeta.urn,
            ColumnMeta.raw_type,
            ColumnMeta.logical_type,
            ColumnMeta.raw_comment,
        ).where(ColumnMeta.is_deleted.is_(False))
    )
    return [
        (name, urn, raw_type, logical_type, comment)
        for name, urn, raw_type, logical_type, comment in rows
        if name not in excluded_names
    ]


async def generate_standard_field_candidates(session: AsyncSession) -> ClusteringSummary:
    """按字段名聚类生成/刷新 DRAFT 候选标准定义。

    幂等可重跑：已有 DRAFT 候选更新统计并整体替换源字段关联；
    已 CONFIRMED 的同名标准不动（定版结论优先于重新聚类）。
    """
    summary = ClusteringSummary()
    rows = await load_cluster_rows(session)
    candidates = build_name_clusters(rows)

    existing = await session.execute(
        select(StandardField).where(
            StandardField.standard_name.in_([c.column_name for c in candidates] or [""])
        )
    )
    existing_by_name = {sf.standard_name: sf for sf in existing.scalars()}

    for candidate in candidates:
        current = existing_by_name.get(candidate.column_name)
        if current is not None and current.status == "CONFIRMED":
            summary.skipped_confirmed += 1
            continue

        distribution = candidate.type_distribution
        if current is None:
            standard = StandardField(
                standard_name=candidate.column_name,
                business_meaning=candidate.suggested_meaning,
                logical_type=candidate.recommended_logical_type or "STRING",
                # 冲突组不给自动推荐类型，等人工裁决
                raw_type=None if candidate.has_conflict else candidate.recommended_raw_type,
                status="DRAFT",
                source_type="CLUSTER",
                has_conflict=candidate.has_conflict,
                type_distribution=distribution,
                candidate_count=candidate.candidate_count,
            )
            session.add(standard)
            await session.flush()
            session.add_all(
                StandardFieldItem(standard_field_id=standard.id, column_urn=urn)
                for urn in candidate.column_urns
            )
            summary.generated += 1
            if candidate.has_conflict:
                summary.skipped_conflict += 1
        else:
            current.business_meaning = current.business_meaning or candidate.suggested_meaning
            current.type_distribution = distribution
            current.candidate_count = candidate.candidate_count
            current.has_conflict = candidate.has_conflict
            current.source_type = "CLUSTER"
            if not current.has_conflict:
                current.logical_type = candidate.recommended_logical_type or current.logical_type
                current.raw_type = candidate.recommended_raw_type
            else:
                current.raw_type = None
            await session.execute(
                delete(StandardFieldItem).where(StandardFieldItem.standard_field_id == current.id)
            )
            session.add_all(
                StandardFieldItem(standard_field_id=current.id, column_urn=urn)
                for urn in candidate.column_urns
            )
            summary.updated += 1

    return summary


async def count_candidates(session: AsyncSession) -> int:
    result = await session.execute(
        select(func.count()).select_from(StandardField).where(StandardField.status == "DRAFT")
    )
    return int(result.scalar_one())


def _to_out(sf: StandardField) -> StandardFieldOut:
    return StandardFieldOut(
        id=sf.id,
        standard_name=sf.standard_name,
        business_meaning=sf.business_meaning,
        logical_type=sf.logical_type,
        raw_type=sf.raw_type,
        status=sf.status,
        source_type=sf.source_type,
        has_conflict=sf.has_conflict,
        type_distribution=sf.type_distribution,
        candidate_count=sf.candidate_count,
        version=sf.version,
    )


async def list_standard_fields(
    session: AsyncSession,
    *,
    status_filter: str | None = None,
    conflict_only: bool = False,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[StandardFieldOut]]:
    stmt = select(StandardField)
    if status_filter:
        stmt = stmt.where(StandardField.status == status_filter)
    if conflict_only:
        stmt = stmt.where(StandardField.has_conflict.is_(True))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                StandardField.standard_name.ilike(like),
                StandardField.business_meaning.ilike(like),
            )
        )
    total = int(
        (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    )
    rows = await session.execute(
        stmt.order_by(StandardField.candidate_count.desc(), StandardField.id)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return total, [_to_out(sf) for sf in rows.scalars()]


async def get_standard_field_detail(
    session: AsyncSession, standard_id: int
) -> StandardFieldDetailOut:
    sf = await session.get(StandardField, standard_id)
    if sf is None:
        raise NotFoundError("标准字段定义不存在", detail={"id": standard_id})

    rows = await session.execute(
        select(
            StandardFieldItem.column_urn,
            StandardFieldItem.conforms,
            ColumnMeta.column_name,
            ColumnMeta.raw_type,
            ColumnMeta.logical_type,
            TableMeta.db_name,
            TableMeta.table_name,
        )
        .select_from(StandardFieldItem)
        .join(ColumnMeta, ColumnMeta.urn == StandardFieldItem.column_urn)
        .join(TableMeta, TableMeta.urn == ColumnMeta.table_urn)
        .where(StandardFieldItem.standard_field_id == standard_id)
        .order_by(TableMeta.db_name, TableMeta.table_name, ColumnMeta.column_name)
    )
    items = [
        StandardFieldItemOut(
            column_urn=urn,
            db_name=db_name,
            table_name=table_name,
            column_name=column_name,
            raw_type=raw_type,
            logical_type=logical_type,
            conforms=conforms,
        )
        for urn, conforms, column_name, raw_type, logical_type, db_name, table_name in rows
    ]
    out = StandardFieldDetailOut(**_to_out(sf).model_dump(), items=items)
    return out


async def confirm_standard_field(
    session: AsyncSession,
    standard_id: int,
    payload: ConfirmStandardFieldPayload,
    *,
    operator_id: int | None = None,
) -> StandardFieldOut:
    """人工确认定版：写入最终推荐类型与释义，并回算存量字段 conforms。"""
    sf = await session.get(StandardField, standard_id)
    if sf is None:
        raise NotFoundError("标准字段定义不存在", detail={"id": standard_id})
    if sf.status != "DRAFT":
        raise ConflictError("该标准定义已定版或已废弃，不能重复确认", detail={"status": sf.status})

    sf.raw_type = payload.raw_type
    sf.logical_type = payload.logical_type
    sf.business_meaning = payload.business_meaning
    sf.status = "CONFIRMED"
    sf.has_conflict = False
    sf.confirmed_by = operator_id
    sf.confirmed_at = datetime.now(UTC)

    items = (
        (
            await session.execute(
                select(StandardFieldItem).where(StandardFieldItem.standard_field_id == sf.id)
            )
        )
        .scalars()
        .all()
    )
    if items:
        urns = [item.column_urn for item in items]
        col_rows = await session.execute(
            select(ColumnMeta.urn, ColumnMeta.raw_type).where(ColumnMeta.urn.in_(urns))
        )
        raw_by_urn = dict(col_rows.all())
        for item in items:
            item.conforms = raw_by_urn.get(item.column_urn) == payload.raw_type

    await session.flush()
    return _to_out(sf)


async def _load_tags(
    session: AsyncSession, standard_ids: list[int]
) -> dict[int, list[StandardFieldTagOut]]:
    if not standard_ids:
        return {}
    urns = [_standard_tag_urn(sid) for sid in standard_ids]
    rows = await session.execute(
        select(AssetTagRel.urn, Tag.id, Tag.name)
        .join(Tag, Tag.id == AssetTagRel.tag_id)
        .where(AssetTagRel.urn.in_(urns))
        .order_by(Tag.name)
    )
    tags_by_id: dict[int, list[StandardFieldTagOut]] = {}
    for urn, tag_id, name in rows:
        sid = int(urn.split(":", 1)[1])
        tags_by_id.setdefault(sid, []).append(StandardFieldTagOut(id=tag_id, name=name))
    return tags_by_id


async def list_confirmed_standards(
    session: AsyncSession,
    *,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[StandardFieldLibraryOut]]:
    """终版标准定义库列表（含业务标签）。"""
    stmt = select(StandardField).where(StandardField.status == "CONFIRMED")
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                StandardField.standard_name.ilike(like),
                StandardField.business_meaning.ilike(like),
            )
        )
    total = int(
        (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    )
    rows = await session.execute(
        stmt.order_by(StandardField.candidate_count.desc(), StandardField.id)
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    standards = list(rows.scalars())
    tags_by_id = await _load_tags(session, [sf.id for sf in standards])
    items = [
        StandardFieldLibraryOut(**_to_out(sf).model_dump(), tags=tags_by_id.get(sf.id, []))
        for sf in standards
    ]
    return total, items


async def list_tag_options(session: AsyncSession) -> list[str]:
    rows = await session.execute(
        select(Tag.name)
        .where(Tag.category == STANDARD_TAG_CATEGORY, Tag.enabled.is_(True))
        .distinct()
        .order_by(Tag.name)
    )
    return [name for (name,) in rows]


async def attach_tag(
    session: AsyncSession,
    standard_id: int,
    name: str,
    *,
    operator_id: int | None = None,
) -> list[StandardFieldTagOut]:
    """给标准定义打业务标签；标签不存在时自动创建（类别=业务别名）。"""
    sf = await session.get(StandardField, standard_id)
    if sf is None:
        raise NotFoundError("标准字段定义不存在", detail={"id": standard_id})
    tag_name = name.strip()
    if not tag_name:
        raise DataDictError("标签名不能为空")

    tag = (
        await session.execute(
            select(Tag).where(Tag.category == STANDARD_TAG_CATEGORY, Tag.name == tag_name)
        )
    ).scalar_one_or_none()
    if tag is None:
        tag = Tag(category=STANDARD_TAG_CATEGORY, code=tag_name, name=tag_name)
        session.add(tag)
        await session.flush()

    urn = _standard_tag_urn(standard_id)
    exists = (
        await session.execute(
            select(AssetTagRel.id).where(AssetTagRel.urn == urn, AssetTagRel.tag_id == tag.id)
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(AssetTagRel(urn=urn, tag_id=tag.id, created_by=operator_id))
    await session.flush()
    return (await _load_tags(session, [standard_id])).get(standard_id, [])


async def detach_tag(
    session: AsyncSession, standard_id: int, tag_id: int
) -> list[StandardFieldTagOut]:
    sf = await session.get(StandardField, standard_id)
    if sf is None:
        raise NotFoundError("标准字段定义不存在", detail={"id": standard_id})
    await session.execute(
        delete(AssetTagRel).where(
            AssetTagRel.urn == _standard_tag_urn(standard_id), AssetTagRel.tag_id == tag_id
        )
    )
    await session.flush()
    return (await _load_tags(session, [standard_id])).get(standard_id, [])
