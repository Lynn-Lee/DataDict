"""标准字段定义：同名聚类候选生成（字段统一治理 T-S2）。

治理路径：存量字段原样同步 → 按字段名聚类产出候选标准定义（零标注成本）→
人工确认定版 → 对外提供设计态查询。同名字段在多数系统中本来就叫法一致，
字段名即最强的语义先验；同名不同型自动标记冲突，强制人工裁决。
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.type_mapper import normalize_column_type
from app.core.exceptions import ConflictError, DataDictError, NotFoundError
from app.models.knowledge import (
    AssetTagRel,
    CommonColumnBlacklist,
    ExcelFieldDoc,
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
    """单个字段名聚合出的候选标准定义（源库 + Excel 文档两路并集）。"""

    column_name: str
    candidate_count: int
    type_distribution: dict[str, int]
    recommended_logical_type: str | None
    recommended_raw_type: str | None
    has_conflict: bool
    suggested_meaning: str | None
    column_urns: list[str] = field(default_factory=list)
    doc_count: int = 0


@dataclass
class ClusteringSummary:
    generated: int = 0
    updated: int = 0
    skipped_confirmed: int = 0
    skipped_conflict: int = 0


def build_name_clusters(
    sync_rows: Iterable[tuple[str, str, str, str | None, str | None]],
    doc_rows: Iterable[tuple[str, str | None, str | None]] = (),
    *,
    excluded_names: set[str] | None = None,
) -> list[ClusterCandidate]:
    """按字段名聚合两路来源，产出候选标准定义。

    - `sync_rows`：(column_name, urn, raw_type, logical_type, raw_comment)，源库实际用法
    - `doc_rows`：(column_name, column_type, column_desc)，Excel 历史文档

    两路是**并集**关系：只在一路出现的字段名同样产出候选（Excel 里有、源库还没同步的
    字段可以先定标准）。推荐规则：类型取合并后的众数；逻辑类型不一致 → has_conflict
    强制人工裁决；释义取两路中最高频的非空描述，仅作确认时的预填。
    """
    excluded = excluded_names or set()
    types: dict[str, Counter[str]] = defaultdict(Counter)
    logicals: dict[str, Counter[str]] = defaultdict(Counter)
    meanings: dict[str, Counter[str]] = defaultdict(Counter)
    urns: dict[str, list[str]] = defaultdict(list)
    doc_counts: dict[str, int] = defaultdict(int)

    for column_name, urn, raw_type, logical_type, raw_comment in sync_rows:
        if column_name in excluded:
            continue
        types[column_name][raw_type] += 1
        if logical_type:
            logicals[column_name][logical_type] += 1
        if raw_comment and raw_comment.strip():
            meanings[column_name][raw_comment.strip()] += 1
        urns[column_name].append(urn)

    for column_name, column_type, column_desc in doc_rows:
        if column_name in excluded:
            continue
        doc_counts[column_name] += 1
        if column_type and column_type.strip():
            # Excel 里存在全角括号写法（varchar（32）），归一后再计数，避免污染类型分布
            raw = column_type.strip().replace("（", "(").replace("）", ")")
            types[column_name][raw] += 1
            # Excel 未标明库类型，按 MySQL 方言归一（历史字典以 MySQL/TiDB 为主）
            normalized = normalize_column_type("mysql", raw)
            if normalized != "UNKNOWN":
                logicals[column_name][normalized] += 1
        if column_desc and column_desc.strip():
            meanings[column_name][column_desc.strip()] += 1

    candidates: list[ClusterCandidate] = []
    for column_name in set(types) | set(urns) | set(doc_counts):
        type_counter = types[column_name]
        logical_counter = logicals[column_name]
        meaning_counter = meanings[column_name]
        top_raw = type_counter.most_common(1)[0][0] if type_counter else None
        top_logical = logical_counter.most_common(1)[0][0] if logical_counter else None
        candidates.append(
            ClusterCandidate(
                column_name=column_name,
                candidate_count=len(urns[column_name]),
                type_distribution=dict(sorted(type_counter.items(), key=lambda kv: -kv[1])),
                recommended_logical_type=top_logical,
                recommended_raw_type=top_raw,
                has_conflict=len(logical_counter) > 1,
                suggested_meaning=(
                    meaning_counter.most_common(1)[0][0] if meaning_counter else None
                ),
                column_urns=list(urns[column_name]),
                doc_count=doc_counts[column_name],
            )
        )
    candidates.sort(key=lambda c: (-c.candidate_count, -c.doc_count))
    return candidates


async def load_excluded_names(session: AsyncSession) -> set[str]:
    """黑名单字段名：同名不同义风险高，不参与自动聚类。"""
    rows = await session.execute(
        select(CommonColumnBlacklist.column_name).where(
            CommonColumnBlacklist.is_whitelist.is_(False)
        )
    )
    return {name for (name,) in rows}


async def load_cluster_rows(
    session: AsyncSession, excluded_names: set[str] | None = None
) -> list[tuple[str, str, str, str, str | None]]:
    """源库侧聚类输入：未删除字段的 (字段名, urn, 原始类型, 逻辑类型, 注释)。"""
    excluded = excluded_names if excluded_names is not None else await load_excluded_names(session)
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
        if name not in excluded
    ]


async def load_doc_rows(
    session: AsyncSession, excluded_names: set[str] | None = None
) -> list[tuple[str, str | None, str | None]]:
    """Excel 文档侧聚类输入：留档的 (字段名, 文档类型, 字段描述)。"""
    excluded = excluded_names if excluded_names is not None else await load_excluded_names(session)
    rows = await session.execute(
        select(ExcelFieldDoc.column_name, ExcelFieldDoc.column_type, ExcelFieldDoc.column_desc)
    )
    return [
        (name, column_type, column_desc)
        for name, column_type, column_desc in rows
        if name not in excluded
    ]


async def generate_standard_field_candidates(session: AsyncSession) -> ClusteringSummary:
    """按字段名聚类（源库 ∪ Excel 文档）生成/刷新 DRAFT 候选标准定义。

    幂等可重跑：已有 DRAFT 候选更新统计并整体替换源字段关联；
    已 CONFIRMED 的同名标准不动（定版结论优先于重新聚类）。
    """
    summary = ClusteringSummary()
    excluded = await load_excluded_names(session)
    sync_rows = await load_cluster_rows(session, excluded)
    doc_rows = await load_doc_rows(session, excluded)
    candidates = build_name_clusters(sync_rows, doc_rows)

    existing = await session.execute(
        select(StandardField).where(
            StandardField.standard_name.in_([c.column_name for c in candidates] or [""])
        )
    )
    existing_by_name = {sf.standard_name: sf for sf in existing.scalars()}

    for candidate in candidates:
        current = existing_by_name.get(candidate.column_name)
        if current is not None and current.status == "CONFIRMED":
            # 定版结论不可被重新聚类覆盖，但证据计数是事实数据，保持最新
            current.candidate_count = candidate.candidate_count
            current.doc_count = candidate.doc_count
            current.type_distribution = candidate.type_distribution
            summary.skipped_confirmed += 1
            continue

        distribution = candidate.type_distribution
        if current is None:
            standard = StandardField(
                standard_name=candidate.column_name,
                business_meaning=candidate.suggested_meaning,
                logical_type=candidate.recommended_logical_type or "UNKNOWN",
                # 冲突组不给自动推荐类型，等人工裁决
                raw_type=None if candidate.has_conflict else candidate.recommended_raw_type,
                status="DRAFT",
                source_type="CLUSTER",
                has_conflict=candidate.has_conflict,
                type_distribution=distribution,
                candidate_count=candidate.candidate_count,
                doc_count=candidate.doc_count,
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
            current.doc_count = candidate.doc_count
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
        doc_count=sf.doc_count,
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
