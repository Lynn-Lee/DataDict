"""标准字段定义：同名聚类候选生成（字段统一治理 T-S2 / T-S11）。

治理路径：存量字段原样同步 → 按字段名聚类产出候选标准定义（零标注成本）→
人工确认定版 → 对外提供设计态查询。同名字段在多数系统中本来就叫法一致，
字段名即最强的语义先验；同名不同型自动标记冲突，强制人工裁决。
通用字段名（status/type 等）同名不同义，不按名整体聚，而按「字段名 + 释义」
拆成多组候选，让它们也能各自定版，而不是被排除在标准库之外。
"""

import hashlib
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Text, column, delete, func, or_, select, values
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
    SimilarStandardOut,
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
    """一个候选标准定义分组。

    普通字段名按名字聚（sub_key=''）；通用字段名（status/type 等同名不同义）
    按「字段名 + 释义」聚，sub_key 存该组释义哈希。
    """

    column_name: str
    candidate_count: int
    type_distribution: dict[str, int]
    recommended_logical_type: str | None
    recommended_raw_type: str | None
    has_conflict: bool
    suggested_meaning: str | None
    column_urns: list[str] = field(default_factory=list)
    doc_count: int = 0
    sub_key: str = ""


@dataclass
class ClusteringSummary:
    generated: int = 0
    updated: int = 0
    skipped_confirmed: int = 0
    skipped_conflict: int = 0


def normalize_meaning(text_value: str | None) -> str:
    """释义分组用的归一：合并空白、去尾部标点、转小写。

    只做「同一句话的写法差异」的归一（空格、句号、冒号），不做语义归一：
    「运单状态」和「订单状态」仍是两组，交由人工裁决或合并。
    """
    if not text_value:
        return ""
    collapsed = " ".join(text_value.split())
    return collapsed.rstrip("。.;；,，:：").lower()


def meaning_key(text_value: str | None) -> str:
    """释义分组哈希。空释义用固定占位，保证与任何有释义的组不同桶。"""
    normalized = normalize_meaning(text_value)
    payload = normalized if normalized else "∅无释义"
    # blake2b 仅作分组键（非安全用途），比 md5 短且不会被安全类 lint 拦
    return hashlib.blake2b(payload.encode("utf-8"), digest_size=8).hexdigest()[:12]


def build_name_clusters(
    sync_rows: Iterable[tuple[str, str, str, str | None, str | None]],
    doc_rows: Iterable[tuple[str, str | None, str | None]] = (),
    *,
    split_names: Iterable[str] = (),
) -> list[ClusterCandidate]:
    """按字段名（通用名再按释义）聚合源库与 Excel 两路证据，产出候选标准定义。

    - `sync_rows`：(column_name, urn, raw_type, logical_type, raw_comment)，源库实际用法
    - `doc_rows`：(column_name, column_type, column_desc)，Excel 历史文档
    - `split_names`：同名不同义风险的通用字段名（黑名单）。这些名字**不再被排除**，
      而是按「字段名 + 释义」分组，让 `status`(运单状态) 与 `status`(工单状态)
      各自成为独立候选——否则这些字段永远进不了标准库。

    两路证据是并集关系：只在一路出现的字段名同样产候选。推荐规则：类型取合并后
    众数；逻辑类型不一致 → has_conflict 强制人工裁决；释义取组内最高频描述。
    """
    split = set(split_names)
    types: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    logicals: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    meanings: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    urns: dict[tuple[str, str], list[str]] = defaultdict(list)
    doc_counts: dict[tuple[str, str], int] = defaultdict(int)

    for column_name, urn, raw_type, logical_type, raw_comment in sync_rows:
        key = (column_name, meaning_key(raw_comment) if column_name in split else "")
        types[key][raw_type] += 1
        if logical_type:
            logicals[key][logical_type] += 1
        if raw_comment and raw_comment.strip():
            meanings[key][raw_comment.strip()] += 1
        urns[key].append(urn)

    for column_name, column_type, column_desc in doc_rows:
        key = (column_name, meaning_key(column_desc) if column_name in split else "")
        doc_counts[key] += 1
        if column_type and column_type.strip():
            # Excel 里存在全角括号写法（varchar（32）），归一后再计数，避免污染类型分布
            raw = column_type.strip().replace("（", "(").replace("）", ")")
            types[key][raw] += 1
            # Excel 未标明库类型，按 MySQL 方言归一（历史字典以 MySQL/TiDB 为主）
            normalized = normalize_column_type("mysql", raw)
            if normalized != "UNKNOWN":
                logicals[key][normalized] += 1
        if column_desc and column_desc.strip():
            meanings[key][column_desc.strip()] += 1

    candidates: list[ClusterCandidate] = []
    for column_name, sub_key in set(types) | set(urns) | set(doc_counts):
        key = (column_name, sub_key)
        type_counter = types[key]
        logical_counter = logicals[key]
        meaning_counter = meanings[key]
        top_raw = type_counter.most_common(1)[0][0] if type_counter else None
        top_logical = logical_counter.most_common(1)[0][0] if logical_counter else None
        candidates.append(
            ClusterCandidate(
                column_name=column_name,
                candidate_count=len(urns[key]),
                type_distribution=dict(sorted(type_counter.items(), key=lambda kv: -kv[1])),
                recommended_logical_type=top_logical,
                recommended_raw_type=top_raw,
                has_conflict=len(logical_counter) > 1,
                suggested_meaning=(
                    meaning_counter.most_common(1)[0][0] if meaning_counter else None
                ),
                column_urns=list(urns[key]),
                doc_count=doc_counts[key],
                sub_key=sub_key,
            )
        )
    candidates.sort(key=lambda c: (-c.candidate_count, -c.doc_count))
    return candidates


async def load_split_names(session: AsyncSession) -> set[str]:
    """通用字段名黑名单：同名不同义风险高，聚类时按「字段名 + 释义」再分组。"""
    rows = await session.execute(
        select(CommonColumnBlacklist.column_name).where(
            CommonColumnBlacklist.is_whitelist.is_(False)
        )
    )
    return {name for (name,) in rows}


async def load_cluster_rows(
    session: AsyncSession, *, column_names: set[str] | None = None
) -> list[tuple[str, str, str, str, str | None]]:
    """源库侧聚类输入：未删除字段的 (字段名, urn, 原始类型, 逻辑类型, 注释)。

    `column_names` 限定只取这些字段名（同步后增量聚类用）；留空取全库。
    """
    stmt = select(
        ColumnMeta.column_name,
        ColumnMeta.urn,
        ColumnMeta.raw_type,
        ColumnMeta.logical_type,
        ColumnMeta.raw_comment,
    ).where(ColumnMeta.is_deleted.is_(False))
    if column_names is not None:
        if not column_names:
            return []
        stmt = stmt.where(ColumnMeta.column_name.in_(sorted(column_names)))
    rows = await session.execute(stmt)
    return [
        (name, urn, raw_type, logical_type, comment)
        for name, urn, raw_type, logical_type, comment in rows
    ]


async def load_doc_rows(
    session: AsyncSession, *, column_names: set[str] | None = None
) -> list[tuple[str, str | None, str | None]]:
    """Excel 文档侧聚类输入：留档的 (字段名, 文档类型, 字段描述)。"""
    stmt = select(ExcelFieldDoc.column_name, ExcelFieldDoc.column_type, ExcelFieldDoc.column_desc)
    if column_names is not None:
        if not column_names:
            return []
        stmt = stmt.where(ExcelFieldDoc.column_name.in_(sorted(column_names)))
    rows = await session.execute(stmt)
    return [(name, column_type, column_desc) for name, column_type, column_desc in rows]


async def generate_standard_field_candidates(
    session: AsyncSession, *, column_names: set[str] | None = None
) -> ClusteringSummary:
    """按字段名（通用名再按释义）聚类，源库 ∪ Excel 文档，生成/刷新 DRAFT 候选。

    幂等可重跑：已有 DRAFT 候选更新统计并整体替换源字段关联；
    已 CONFIRMED 的同名标准不动（定版结论优先于重新聚类）。

    `column_names` 给定时只重聚这些字段名（同步后增量用）。注意按**字段名**而非按
    字段过滤：同名的全部存量字段都要参与计数，否则类型分布与 candidate_count 会失真。
    """
    summary = ClusteringSummary()
    split_names = await load_split_names(session)
    sync_rows = await load_cluster_rows(session, column_names=column_names)
    doc_rows = await load_doc_rows(session, column_names=column_names)
    candidates = build_name_clusters(sync_rows, doc_rows, split_names=split_names)

    # 按 (cluster_key, sub_key) 匹配既有候选：标准可能被改名或合并，用来源字段名+
    # 释义分组匹配才不会在重新聚类时把同一批字段又产出一个新候选（标准库出现重复概念）。
    existing = await session.execute(
        select(StandardField).where(
            StandardField.cluster_key.in_([c.column_name for c in candidates] or [""])
        )
    )
    existing_by_key = {
        (sf.cluster_key, sf.sub_key): sf for sf in existing.scalars() if sf.cluster_key
    }

    for candidate in candidates:
        current = existing_by_key.get((candidate.column_name, candidate.sub_key))
        if current is not None and current.status in {"CONFIRMED", "MERGED"}:
            # 定版/已合并的结论不可被重新聚类覆盖，但证据计数是事实数据，保持最新
            current.candidate_count = candidate.candidate_count
            current.doc_count = candidate.doc_count
            current.type_distribution = candidate.type_distribution
            summary.skipped_confirmed += 1
            continue

        distribution = candidate.type_distribution
        if current is None:
            standard = StandardField(
                standard_name=candidate.column_name,
                cluster_key=candidate.column_name,
                sub_key=candidate.sub_key,
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
        cluster_key=sf.cluster_key,
        sub_key=sf.sub_key,
        merged_into_id=sf.merged_into_id,
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
    else:
        # 已合并的候选不再是独立条目，默认不列出
        stmt = stmt.where(StandardField.status != "MERGED")
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
    items = [_to_out(sf) for sf in rows.scalars()]
    similar = await find_similar_standards(session, items)
    for item in items:
        item.similar_standards = similar.get(item.id, [])
    return total, items


# 释义相似度阈值：中文短文本 trigram 相似度天然偏低，但过低会把「订单编号 / 运单编号」
# 这类仅共享后缀词的无关概念也提示出来。0.2 在真实数据上能留住 site_code→send_site_code
# 这类真同义，滤掉共享词噪音；NAME/ALIAS 是强信号，不受此阈值影响。
# 提示只是建议（用户一眼可否），漏提示才会产生重复标准，故阈值调整应偏保守。
SIMILAR_MEANING_THRESHOLD = 0.2
SIMILAR_TOP_N = 3


async def find_similar_standards(
    session: AsyncSession, candidates: list[StandardFieldOut]
) -> dict[int, list[SimilarStandardOut]]:
    """为候选找出标准库中可能已存在的同义标准。

    三路信号，强弱依次：① 同名（NAME）② 命中已有标准的业务别名（ALIAS）
    ③ 释义 pg_trgm 相似（MEANING）。目的是在用户确认前就告诉他
    “这个概念标准库里已经有了”，避免定版出第二个同义标准。
    """
    drafts = [c for c in candidates if c.status == "DRAFT"]
    if not drafts:
        return {}

    confirmed = (
        (await session.execute(select(StandardField).where(StandardField.status == "CONFIRMED")))
        .scalars()
        .all()
    )
    if not confirmed:
        return {}
    by_id = {std.id: std for std in confirmed}
    # 同名即同概念的强信号只在「按字段名整体定标」的标准之间成立；释义拆组出来的标准
    # 名字是 status/type 这类通用名，按名命中会把用户推向另一个同名不同义的概念。
    by_name = {std.standard_name.lower(): std for std in confirmed if not std.sub_key}

    alias_rows = await session.execute(
        select(Tag.name, AssetTagRel.urn)
        .join(AssetTagRel, AssetTagRel.tag_id == Tag.id)
        .where(Tag.category == STANDARD_TAG_CATEGORY)
    )
    alias_to_std: dict[str, StandardField] = {}
    for alias, urn in alias_rows:
        std = by_id.get(int(urn.split(":", 1)[1]))
        if std is not None:
            alias_to_std.setdefault(alias.lower(), std)

    meaning_pairs = [(c.id, c.business_meaning) for c in drafts if c.business_meaning]
    sim_by_candidate: dict[int, list[tuple[int, float]]] = defaultdict(list)
    if meaning_pairs:
        cand = values(column("cid", BigInteger), column("meaning", Text), name="cand").data(
            meaning_pairs
        )
        score = func.similarity(StandardField.business_meaning, cand.c.meaning)
        rows = await session.execute(
            select(cand.c.cid, StandardField.id, score.label("score"))
            .select_from(cand, StandardField)
            .where(
                StandardField.status == "CONFIRMED",
                StandardField.business_meaning.is_not(None),
                score >= SIMILAR_MEANING_THRESHOLD,
            )
            .order_by(cand.c.cid, score.desc())
        )
        for cid, sid, sim_score in rows:
            sim_by_candidate[int(cid)].append((int(sid), float(sim_score)))

    result: dict[int, list[SimilarStandardOut]] = {}
    for candidate in drafts:
        keys = {candidate.standard_name.lower()}
        if candidate.cluster_key:
            keys.add(candidate.cluster_key.lower())

        picked: dict[int, SimilarStandardOut] = {}
        for key in keys:
            if key in by_name:
                std = by_name[key]
                picked[std.id] = _similar(std, "NAME", 1.0)
            if key in alias_to_std:
                std = alias_to_std[key]
                picked.setdefault(std.id, _similar(std, "ALIAS", 1.0))
        for sid, sim_score in sim_by_candidate.get(candidate.id, []):
            if sid in picked:
                continue
            std = by_id[sid]
            picked[sid] = _similar(std, "MEANING", round(sim_score, 3))

        ordered = sorted(
            picked.values(),
            key=lambda s: (0 if s.matched_by in {"NAME", "ALIAS"} else 1, -s.score),
        )
        if ordered:
            result[candidate.id] = ordered[:SIMILAR_TOP_N]
    return result


def _similar(std: StandardField, matched_by: str, score: float) -> SimilarStandardOut:
    return SimilarStandardOut(
        id=std.id,
        standard_name=std.standard_name,
        raw_type=std.raw_type,
        business_meaning=std.business_meaning,
        matched_by=matched_by,
        score=score,
    )


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
    """人工确认定版：字段名/类型/长度/释义均可改，并回算存量字段 conforms。

    标准名可以被改（例如把 bill_code 组定版为 waybill_no）；若改名后与库中已有的
    活跃标准重名，说明这是同一个概念，返回 409 并给出目标标准，由调用方改走
    合并（merge_standard_field），避免标准库出现两个同义标准。

    通用字段名（status/type 等）按释义拆组后，同名的不同释义组可以各自定版共存
    （沿用来源名定版不算改名，不触发上面的重名拦截）。

    conforms 口径 = 字段名与类型**都**符合标准（标准叫 waybill_no varchar(16)，
    存量叫 bill_code varchar(32) 即为不符合），这样符合率才反映真实治理进度。
    """
    sf = await session.get(StandardField, standard_id)
    if sf is None:
        raise NotFoundError("标准字段定义不存在", detail={"id": standard_id})
    if sf.status != "DRAFT":
        raise ConflictError("该标准定义已定版或已废弃，不能重复确认", detail={"status": sf.status})

    new_name = (payload.standard_name or sf.standard_name).strip()
    if not new_name:
        raise DataDictError("标准字段名不能为空")
    old_name = sf.standard_name
    if new_name != sf.standard_name:
        clash = (
            (
                await session.execute(
                    select(StandardField).where(
                        StandardField.standard_name == new_name,
                        StandardField.status.in_(["DRAFT", "CONFIRMED"]),
                        StandardField.id != sf.id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if clash is not None:
            raise ConflictError(
                f"标准库已存在「{new_name}」，同一概念只应有一个标准，请改为关联到该标准",
                detail={
                    "existing_id": clash.id,
                    "existing_name": clash.standard_name,
                    "existing_raw_type": clash.raw_type,
                    "existing_status": clash.status,
                },
            )

    sf.standard_name = new_name
    sf.raw_type = payload.raw_type
    sf.logical_type = payload.logical_type
    sf.business_meaning = payload.business_meaning
    sf.status = "CONFIRMED"
    sf.has_conflict = False
    sf.confirmed_by = operator_id
    sf.confirmed_at = datetime.now(UTC)

    # 改名定版时把来源字段名沉淀为业务别名（与合并一致），后续同名候选可按 ALIAS
    # 命中本标准；释义拆组候选的名字是通用名（status 等），沉淀会误引所有同名字段，故不记。
    if new_name != old_name and not sf.sub_key:
        await attach_tag(session, sf.id, old_name, operator_id=operator_id)

    await recompute_conforms(session, sf)
    await session.flush()
    return _to_out(sf)


async def recompute_conforms(session: AsyncSession, sf: StandardField) -> int:
    """按「字段名 + 类型都一致」回算组内存量字段的 conforms，返回不符合数。"""
    items = (
        (
            await session.execute(
                select(StandardFieldItem).where(StandardFieldItem.standard_field_id == sf.id)
            )
        )
        .scalars()
        .all()
    )
    if not items:
        return 0
    urns = [item.column_urn for item in items]
    col_rows = await session.execute(
        select(ColumnMeta.urn, ColumnMeta.column_name, ColumnMeta.raw_type).where(
            ColumnMeta.urn.in_(urns)
        )
    )
    cols = {urn: (name, raw_type) for urn, name, raw_type in col_rows}
    deviating = 0
    for item in items:
        found = cols.get(item.column_urn)
        item.conforms = bool(found and found[0] == sf.standard_name and found[1] == sf.raw_type)
        if not item.conforms:
            deviating += 1
    return deviating


async def merge_standard_field(
    session: AsyncSession,
    source_id: int,
    target_id: int,
    *,
    operator_id: int | None = None,
) -> StandardFieldOut:
    """把候选合并进已有的同义标准（不产生第二个标准）。

    - 候选的存量字段关联迁到目标标准下，重复的跳过
    - 候选置 MERGED 并记录 merged_into_id
    - 候选的来源字段名记为目标的业务别名标签，供后续同步按别名拦截新增违规
    - 目标的 conforms 按「名 + 型」重算（迁进来的异名字段自然标记为不符合）

    目标可以是已定版标准（常见：bill_code 组关联进 waybill_no 标准），也可以是
    另一个待确认候选（同义候选先归并再一起定版）；已合并/已废弃的不能作目标。
    """
    if source_id == target_id:
        raise DataDictError("不能合并到自身")
    source = await session.get(StandardField, source_id)
    target = await session.get(StandardField, target_id)
    if source is None or target is None:
        raise NotFoundError("标准字段定义不存在", detail={"source": source_id, "target": target_id})
    if target.status in {"MERGED", "DEPRECATED"}:
        raise ConflictError(
            "目标标准已合并或已废弃，不能作为合并目标", detail={"target_status": target.status}
        )
    if source.status == "MERGED":
        raise ConflictError("该候选已合并过", detail={"merged_into_id": source.merged_into_id})

    existing_urns = set(
        (
            await session.execute(
                select(StandardFieldItem.column_urn).where(
                    StandardFieldItem.standard_field_id == target.id
                )
            )
        ).scalars()
    )
    moved = (
        (
            await session.execute(
                select(StandardFieldItem).where(StandardFieldItem.standard_field_id == source.id)
            )
        )
        .scalars()
        .all()
    )
    for item in moved:
        if item.column_urn in existing_urns:
            await session.delete(item)
            continue
        item.standard_field_id = target.id
        existing_urns.add(item.column_urn)

    alias = source.cluster_key or source.standard_name
    source.status = "MERGED"
    source.merged_into_id = target.id
    await session.flush()

    # 释义拆组候选的名字是 status/type 这类通用名，沉淀成别名会把后续所有同名字段
    # 都引向这一个标准，正好制造本次要解决的「同名不同义被并成一个」问题，故不记别名。
    if alias and alias != target.standard_name and not source.sub_key:
        await attach_tag(session, target.id, alias, operator_id=operator_id)

    target.candidate_count = len(existing_urns)
    await recompute_conforms(session, target)
    await session.flush()
    return _to_out(target)


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
