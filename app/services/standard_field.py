"""标准字段定义：同名聚类候选生成（字段统一治理 T-S2）。

治理路径：存量字段原样同步 → 按字段名聚类产出候选标准定义（零标注成本）→
人工确认定版 → 对外提供设计态查询。同名字段在多数系统中本来就叫法一致，
字段名即最强的语义先验；同名不同型自动标记冲突，强制人工裁决。
"""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import CommonColumnBlacklist, StandardField, StandardFieldItem
from app.models.metadata import ColumnMeta


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
            if candidate.has_conflict:
                # 冲突组直接建 DRAFT 但不填推荐类型，等人工裁决
                session.add(
                    StandardField(
                        standard_name=candidate.column_name,
                        business_meaning=candidate.suggested_meaning,
                        logical_type=candidate.recommended_logical_type or "STRING",
                        raw_type=None,
                        status="DRAFT",
                        source_type="CLUSTER",
                        has_conflict=True,
                        type_distribution=distribution,
                        candidate_count=candidate.candidate_count,
                    )
                )
                summary.skipped_conflict += 1
                continue
            standard = StandardField(
                standard_name=candidate.column_name,
                business_meaning=candidate.suggested_meaning,
                logical_type=candidate.recommended_logical_type or "STRING",
                raw_type=candidate.recommended_raw_type,
                status="DRAFT",
                source_type="CLUSTER",
                has_conflict=False,
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
        else:
            current.business_meaning = current.business_meaning or candidate.suggested_meaning
            current.type_distribution = distribution
            current.candidate_count = candidate.candidate_count
            current.has_conflict = candidate.has_conflict
            current.source_type = "CLUSTER"
            if not current.has_conflict:
                current.logical_type = candidate.recommended_logical_type or current.logical_type
                current.raw_type = candidate.recommended_raw_type
                await session.execute(
                    delete(StandardFieldItem).where(
                        StandardFieldItem.standard_field_id == current.id
                    )
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
