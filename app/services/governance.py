"""同步后治理联动：存量字段 × 已定版标准比对（T-S8a / T-S12）。

采集流程（collector 角色）对知识层无写权限——DEV-TASKS §7 红线第 6 条。
因此比对不在同步事务内做，而是同步完成后由本服务用 web 会话执行，幂等可重跑：

- 活跃字段按「字段名」匹配已定版标准；通用字段名（status/type 等同名不同义）
  已按释义拆组，则按「字段名 + 释义哈希」精确命中自己那一组，找不到组的不挂载
- 未挂载的字段 → 挂入 standard_field_item；类型一致 conforms=true，
  不一致 conforms=false 并生成 STANDARD_CONFLICT 治理待办（当周拦截新增混乱）
- 已挂载但类型漂移的字段 → 重算 conforms，漂移为不符合时补待办
- 注释变更导致释义组变化时，把挂在**释义级标准**下的字段重挂到新组（摘掉旧错挂）；
  挂在名级标准下的关联不动——那可能是人工做的异名归组，扫描无权推翻
- 仍未关联任何已定版标准的字段 → 按表聚合产出 STANDARD_MISSING 待办（一表一条，
  缺口清零自动关闭；人工豁免/忽略后只有缺口变大才重新提醒，避免刷屏）

同步后链路由 `run_post_sync_governance()` 提供：先按本轮变更字段做**增量聚类**，
再跑上述扫描；每日兜底 job 跑全量聚类 + 扫描。
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, DataDictError, NotFoundError
from app.db.session import web_session
from app.models.knowledge import StandardField, StandardFieldItem
from app.models.metadata import ColumnMeta, TableMeta
from app.models.support import AnnotationTodo
from app.schemas.governance import (
    GovernanceGapColumn,
    GovernanceTodoOut,
    ResolveTodoPayload,
)
from app.services.standard_field import (
    ClusteringSummary,
    generate_standard_field_candidates,
    meaning_key,
)

GOVERNANCE_TODO_TYPE = "STANDARD_CONFLICT"
# 表级聚合待办：该表仍有字段没关联任何标准定义（缺口提醒，按表开一条而不是按字段刷屏）
MISSING_TODO_TYPE = "STANDARD_MISSING"
# 待办里最多展示的未挂载字段数（完整数量在 missing_count，列表只给预览）
MISSING_PREVIEW_LIMIT = 20


@dataclass
class GovernanceSweepSummary:
    attached_conforming: int = 0
    attached_conflicting: int = 0
    conforms_updated: int = 0
    todos_created: int = 0
    reattached: int = 0
    detached: int = 0
    missing_todos_created: int = 0
    missing_todos_updated: int = 0
    missing_todos_closed: int = 0
    missing_tables: int = 0


def decide_attachment(
    *,
    attached_standard_id: int | None,
    attached_sub_key: str,
    expected_standard_id: int | None,
) -> str:
    """判断一个存量字段与标准组的挂载关系该怎么走：ATTACH / MOVE / DETACH / KEEP。

    - `attached_standard_id` 为空表示还没挂载；`attached_sub_key` 非空表示挂在
      **释义级标准**（通用字段名按释义拆出来的那一组）下
    - `expected_standard_id` 为空表示按「字段名 + 释义」已经找不到任何标准了

    释义级标准的成员定义就是释义哈希，注释变了必须跟着走（MOVE/DETACH）；
    名级标准下的关联可能是人工做的异名归组，扫描不推翻（KEEP）。
    """
    if expected_standard_id is None:
        return "DETACH" if attached_sub_key else "KEEP"
    if attached_standard_id is None:
        return "ATTACH"
    if attached_sub_key and attached_standard_id != expected_standard_id:
        return "MOVE"
    return "KEEP"


def plan_missing_todo(
    *,
    gap_count: int,
    open_missing_count: int | None,
    last_closed_missing_count: int | None,
) -> str:
    """表级缺口待办的生命周期：CREATE / REFRESH / KEEP / CLOSE / SILENT。

    去重口径与冲突待办一致——不能每轮扫描都复活人工已经处理过的提醒：
    已豁免/忽略的表只有在缺口**变大**时才重新开单；缺口清零则自动关闭 OPEN 的那条。
    """
    if gap_count == 0:
        return "CLOSE" if open_missing_count is not None else "KEEP"
    if open_missing_count is not None:
        return "REFRESH" if open_missing_count != gap_count else "KEEP"
    if last_closed_missing_count is not None and gap_count <= last_closed_missing_count:
        return "SILENT"
    return "CREATE"


async def run_governance_sweep(session: AsyncSession) -> GovernanceSweepSummary:
    summary = GovernanceSweepSummary()

    standards = (
        (await session.execute(select(StandardField).where(StandardField.status == "CONFIRMED")))
        .scalars()
        .all()
    )
    if not standards:
        return summary
    # 两级挂载：通用字段名（status/type 等）同名不同义，按「字段名 + 释义哈希」
    # 精确命中自己那一组；其余标准仍按字段名整体命中。
    std_by_name: dict[str, StandardField] = {}
    std_by_meaning: dict[tuple[str, str], StandardField] = {}
    for standard in standards:
        if not standard.sub_key:
            std_by_name[standard.standard_name] = standard
        elif standard.cluster_key:
            std_by_meaning[(standard.cluster_key, standard.sub_key)] = standard

    items = (
        await session.execute(
            select(
                StandardFieldItem,
                StandardField.standard_name,
                StandardField.sub_key,
                StandardField.cluster_key,
            )
            .join(StandardField, StandardField.id == StandardFieldItem.standard_field_id)
            .where(StandardFieldItem.standard_field_id.in_([std.id for std in standards]))
        )
    ).all()
    # 记住每条关联当前挂在哪个标准上（含是否释义级），用于判断注释变更后的重挂
    attached: dict[str, tuple[Any, str, str, str | None]] = {
        item.column_urn: (item, std_name, sub_key, cluster_key)
        for item, std_name, sub_key, cluster_key in items
    }

    # 去重口径：同一字段只要存在过治理待办（无论 OPEN/DONE/IGNORED）就不再重复生成。
    # 否则已豁免/已采纳的字段每次扫描都会新开待办，形成提醒风暴——豁免机制即失效。
    existing_todo_urns = set(
        (
            await session.execute(
                select(AnnotationTodo.urn).where(
                    AnnotationTodo.todo_type == GOVERNANCE_TODO_TYPE,
                )
            )
        ).scalars()
    )

    names = set(std_by_name) | {name for name, _ in std_by_meaning}
    col_rows = await session.execute(
        select(
            ColumnMeta.urn,
            ColumnMeta.column_name,
            ColumnMeta.raw_type,
            ColumnMeta.raw_comment,
        ).where(
            ColumnMeta.is_deleted.is_(False),
            ColumnMeta.column_name.in_(list(names)),
        )
    )

    for urn, column_name, raw_type, raw_comment in col_rows:
        expected = std_by_meaning.get((column_name, meaning_key(raw_comment))) or std_by_name.get(
            column_name
        )
        entry = attached.get(urn)
        item = entry[0] if entry else None
        action = decide_attachment(
            attached_standard_id=None if item is None else item.standard_field_id,
            attached_sub_key=entry[2] if entry else "",
            expected_standard_id=None if expected is None else expected.id,
        )

        if action == "DETACH":
            # 注释变了，原释义组不再成立：摘掉错挂，让它以「未挂标准」重进视野
            await session.delete(item)
            summary.detached += 1
            continue
        if expected is None:
            continue

        conforms = raw_type == expected.raw_type
        if action == "ATTACH":
            session.add(
                StandardFieldItem(standard_field_id=expected.id, column_urn=urn, conforms=conforms)
            )
            if conforms:
                summary.attached_conforming += 1
            else:
                summary.attached_conflicting += 1
        elif action == "MOVE" and item is not None:
            # 释义级标准的成员按释义定义，注释变了必须跟着重挂到新组
            item.standard_field_id = expected.id
            summary.reattached += 1
        if item is not None and item.conforms != conforms:
            item.conforms = conforms
            if action != "MOVE":
                summary.conforms_updated += 1

        if not conforms and urn not in existing_todo_urns:
            session.add(
                AnnotationTodo(
                    urn=urn,
                    todo_type=GOVERNANCE_TODO_TYPE,
                    status="OPEN",
                    priority=1,
                    payload={
                        "standard_field_id": expected.id,
                        "standard_name": expected.standard_name,
                        "expected_type": expected.raw_type,
                        "actual_type": raw_type,
                        "business_meaning": expected.business_meaning,
                    },
                )
            )
            existing_todo_urns.add(urn)
            summary.todos_created += 1

    await session.flush()
    await _sync_missing_todos(session, summary)
    return summary


async def _sync_missing_todos(session: AsyncSession, summary: GovernanceSweepSummary) -> None:
    """未关联任何**已定版**标准的字段 → 按表聚合的 STANDARD_MISSING 待办。

    生命周期：缺口出现开一条；OPEN 期间刷新计数与预览；缺口清零自动关闭；
    人工豁免/忽略后，只有缺口变大才重开——否则每轮扫描都会复活已处理的提醒。
    """
    attached_confirmed = (
        select(StandardFieldItem.column_urn)
        .join(StandardField, StandardField.id == StandardFieldItem.standard_field_id)
        .where(StandardField.status == "CONFIRMED")
        .scalar_subquery()
    )

    gap_rows = await session.execute(
        select(ColumnMeta.table_urn, func.count().label("gap_count"))
        .where(
            ColumnMeta.is_deleted.is_(False),
            ColumnMeta.urn.not_in(attached_confirmed),
        )
        .group_by(ColumnMeta.table_urn)
    )
    gaps = {str(table_urn): int(count) for table_urn, count in gap_rows}

    todos = (
        (
            await session.execute(
                select(AnnotationTodo).where(AnnotationTodo.todo_type == MISSING_TODO_TYPE)
            )
        )
        .scalars()
        .all()
    )
    open_by_table: dict[str, AnnotationTodo] = {}
    last_closed_by_table: dict[str, AnnotationTodo] = {}
    for todo in todos:
        if todo.status == "OPEN":
            open_by_table[todo.urn] = todo
        else:
            previous = last_closed_by_table.get(todo.urn)
            if previous is None or todo.id > previous.id:
                last_closed_by_table[todo.urn] = todo

    def count_of(todo: AnnotationTodo | None) -> int | None:
        if todo is None:
            return None
        return int((todo.payload or {}).get("missing_count", 0))

    plans: dict[str, str] = {}
    for table_urn in set(gaps) | set(open_by_table):
        plans[table_urn] = plan_missing_todo(
            gap_count=gaps.get(table_urn, 0),
            open_missing_count=count_of(open_by_table.get(table_urn)),
            last_closed_missing_count=count_of(last_closed_by_table.get(table_urn)),
        )

    previews = await _load_gap_previews(
        session,
        [table_urn for table_urn, plan in plans.items() if plan in {"CREATE", "REFRESH"}],
    )

    for table_urn, plan in plans.items():
        if plan in {"CREATE", "REFRESH"}:
            summary.missing_tables += 1
        gap_count = gaps.get(table_urn, 0)
        if plan == "CLOSE":
            open_todo = open_by_table[table_urn]
            open_todo.status = "DONE"
            open_todo.done_at = datetime.now(UTC)
            open_todo.payload = {
                **(open_todo.payload or {}),
                "missing_count": 0,
                "action": "AUTO_RESOLVED",
            }
            summary.missing_todos_closed += 1
        elif plan == "REFRESH":
            open_by_table[table_urn].payload = _gap_payload(table_urn, gap_count, previews)
            summary.missing_todos_updated += 1
        elif plan == "CREATE":
            session.add(
                AnnotationTodo(
                    urn=table_urn,
                    todo_type=MISSING_TODO_TYPE,
                    status="OPEN",
                    priority=2,
                    payload=_gap_payload(table_urn, gap_count, previews),
                )
            )
            summary.missing_todos_created += 1

    await session.flush()


async def _load_gap_previews(
    session: AsyncSession, table_urns: list[str]
) -> dict[str, dict[str, Any]]:
    """缺口预览：每张待办表最多取前 MISSING_PREVIEW_LIMIT 个未挂标准字段。"""
    if not table_urns:
        return {}
    attached_confirmed = (
        select(StandardFieldItem.column_urn)
        .join(StandardField, StandardField.id == StandardFieldItem.standard_field_id)
        .where(StandardField.status == "CONFIRMED")
        .scalar_subquery()
    )
    draft_names = set(
        (
            await session.execute(
                select(StandardField.cluster_key).where(StandardField.status == "DRAFT")
            )
        ).scalars()
    )

    rank = (
        func.row_number()
        .over(
            partition_by=ColumnMeta.table_urn,
            order_by=[ColumnMeta.ordinal, ColumnMeta.urn],
        )
        .label("rank")
    )
    ranked = (
        select(
            ColumnMeta.table_urn,
            ColumnMeta.column_name,
            ColumnMeta.raw_type,
            ColumnMeta.raw_comment,
            rank,
        )
        .where(
            ColumnMeta.is_deleted.is_(False),
            ColumnMeta.table_urn.in_(table_urns),
            ColumnMeta.urn.not_in(attached_confirmed),
        )
        .subquery()
    )
    rows = await session.execute(
        select(
            TableMeta.db_name,
            TableMeta.table_name,
            ranked.c.table_urn,
            ranked.c.column_name,
            ranked.c.raw_type,
            ranked.c.raw_comment,
        )
        .join(TableMeta, TableMeta.urn == ranked.c.table_urn)
        .where(ranked.c["rank"] <= MISSING_PREVIEW_LIMIT)
        .order_by(ranked.c.table_urn, ranked.c["rank"])
    )

    previews: dict[str, dict[str, Any]] = {}
    for db_name, table_name, table_urn, column_name, raw_type, raw_comment in rows:
        entry = previews.setdefault(
            table_urn, {"db_name": db_name, "table_name": table_name, "columns": []}
        )
        entry["columns"].append(
            {
                "column_name": column_name,
                "raw_type": raw_type,
                "raw_comment": raw_comment,
                # 该字段名已有 DRAFT 候选 → 动作是「去工作台定版」，不是新建标准
                "has_draft_candidate": column_name in draft_names,
            }
        )
    return previews


def _gap_payload(table_urn: str, count: int, previews: dict[str, dict[str, Any]]) -> dict[str, Any]:
    preview = previews.get(table_urn, {})
    return {
        "table_urn": table_urn,
        "db_name": preview.get("db_name"),
        "table_name": preview.get("table_name"),
        "missing_count": count,
        "missing_columns": preview.get("columns", []),
        "preview_truncated": count > MISSING_PREVIEW_LIMIT,
    }


@dataclass
class PostSyncGovernanceSummary:
    scope: str = "SWEEP_ONLY"
    clustered_columns: int = 0
    clustering: ClusteringSummary = field(default_factory=ClusteringSummary)
    sweep: GovernanceSweepSummary = field(default_factory=GovernanceSweepSummary)


async def _resolve_column_names(session: AsyncSession, column_urns: Sequence[str]) -> set[str]:
    """把本轮变更字段 URN 换成字段名集合——聚类必须按名重算，同名其他字段的计数才不失真。"""
    if not column_urns:
        return set()
    rows = await session.execute(
        select(ColumnMeta.column_name).where(ColumnMeta.urn.in_(sorted(column_urns))).distinct()
    )
    return {str(name) for (name,) in rows}


async def run_post_sync_governance(
    changed_column_urns: Sequence[str] | None = None,
) -> PostSyncGovernanceSummary:
    """同步后治理链路：聚类（可增量）→ 挂载比对 → 缺口待办，自开 web 会话。

    `changed_column_urns`：
    - 传本轮变更字段 URN → 只重聚这些字段名（同步后即时拦截，成本与变更量成正比）
    - 传 None → 全量重聚（每日兜底 job，兜住增量漏网的字段）
    - 传空列表 → 本轮没有字段变更，只做扫描
    """
    async with web_session() as session:
        summary = PostSyncGovernanceSummary()
        if changed_column_urns is None:
            summary.scope = "FULL"
            summary.clustering = await generate_standard_field_candidates(session)
        else:
            names = await _resolve_column_names(session, changed_column_urns)
            summary.clustered_columns = len(names)
            if names:
                summary.scope = "INCREMENTAL"
                summary.clustering = await generate_standard_field_candidates(
                    session, column_names=names
                )
        summary.sweep = await run_governance_sweep(session)
        await session.commit()
        return summary


def _todo_out(
    todo: AnnotationTodo,
    *,
    db_name: str | None,
    table_name: str | None,
    column_name: str | None,
    actual_type: str | None,
) -> GovernanceTodoOut:
    payload = todo.payload or {}
    gap_columns = [
        GovernanceGapColumn(
            column_name=str(item.get("column_name") or ""),
            raw_type=item.get("raw_type"),
            raw_comment=item.get("raw_comment"),
            has_draft_candidate=bool(item.get("has_draft_candidate")),
        )
        for item in payload.get("missing_columns") or []
        if item.get("column_name")
    ]
    return GovernanceTodoOut(
        id=todo.id,
        column_urn=todo.urn,
        todo_type=todo.todo_type,
        db_name=db_name or payload.get("db_name"),
        table_name=table_name or payload.get("table_name"),
        column_name=column_name,
        actual_type=actual_type,
        standard_field_id=payload.get("standard_field_id"),
        standard_name=payload.get("standard_name"),
        expected_type=payload.get("expected_type"),
        business_meaning=payload.get("business_meaning"),
        missing_count=payload.get("missing_count"),
        missing_columns=gap_columns,
        preview_truncated=bool(payload.get("preview_truncated")),
        status=todo.status,
        action=payload.get("action"),
        reason=payload.get("reason"),
        created_at=todo.created_at,
        done_at=todo.done_at,
    )


async def list_governance_todos(
    session: AsyncSession,
    *,
    status: str | None = "OPEN",
    todo_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[GovernanceTodoOut]]:
    # 字段级冲突待办的 URN 是字段，表级缺口待办的 URN 是表——两次外连接都要能落上
    stmt = (
        select(
            AnnotationTodo,
            TableMeta.db_name,
            TableMeta.table_name,
            ColumnMeta.column_name,
            ColumnMeta.raw_type,
        )
        .outerjoin(ColumnMeta, ColumnMeta.urn == AnnotationTodo.urn)
        .outerjoin(
            TableMeta,
            or_(TableMeta.urn == ColumnMeta.table_urn, TableMeta.urn == AnnotationTodo.urn),
        )
        .where(AnnotationTodo.todo_type.in_([GOVERNANCE_TODO_TYPE, MISSING_TODO_TYPE]))
    )
    type_filters = [
        AnnotationTodo.todo_type == todo_type
        if todo_type
        else AnnotationTodo.todo_type.in_([GOVERNANCE_TODO_TYPE, MISSING_TODO_TYPE])
    ]
    if status:
        type_filters.append(AnnotationTodo.status == status)

    total = int(
        (
            await session.execute(
                select(func.count()).select_from(AnnotationTodo).where(*type_filters)
            )
        ).scalar_one()
    )
    rows = await session.execute(
        stmt.where(*type_filters)
        .order_by(
            AnnotationTodo.priority, AnnotationTodo.created_at.desc(), AnnotationTodo.id.desc()
        )
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    items = [
        _todo_out(
            todo,
            db_name=db_name,
            table_name=table_name,
            column_name=column_name,
            actual_type=raw_type,
        )
        for todo, db_name, table_name, column_name, raw_type in rows
    ]
    return total, items


async def resolve_governance_todo(
    session: AsyncSession, todo_id: int, payload: ResolveTodoPayload
) -> GovernanceTodoOut:
    todo = await session.get(AnnotationTodo, todo_id)
    if todo is None or todo.todo_type not in {GOVERNANCE_TODO_TYPE, MISSING_TODO_TYPE}:
        raise NotFoundError("治理待办不存在", detail={"id": todo_id})
    if todo.status != "OPEN":
        raise ConflictError("该待办已处理", detail={"status": todo.status})
    if payload.action == "EXEMPT" and not (payload.reason or "").strip():
        raise DataDictError("豁免必须填写原因（留痕，供治理复盘）")
    if todo.todo_type == MISSING_TODO_TYPE and payload.action == "ADOPT":
        raise DataDictError(
            "表级缺口待办不能直接采纳：请让字段关联到标准（缺口清零后自动关闭），或写明原因豁免"
        )

    todo.status = "DONE" if payload.action == "ADOPT" else "IGNORED"
    todo.done_at = datetime.now(UTC)
    todo.payload = {
        **(todo.payload or {}),
        "action": payload.action,
        "reason": (payload.reason or "").strip() or None,
    }
    await session.flush()

    if todo.todo_type == MISSING_TODO_TYPE:
        table_row = (
            await session.execute(
                select(TableMeta.db_name, TableMeta.table_name).where(TableMeta.urn == todo.urn)
            )
        ).one_or_none()
        db_name, table_name = table_row if table_row else (None, None)
        return _todo_out(
            todo, db_name=db_name, table_name=table_name, column_name=None, actual_type=None
        )

    row = (
        await session.execute(
            select(
                TableMeta.db_name,
                TableMeta.table_name,
                ColumnMeta.column_name,
                ColumnMeta.raw_type,
            )
            .select_from(ColumnMeta)
            .join(TableMeta, TableMeta.urn == ColumnMeta.table_urn)
            .where(ColumnMeta.urn == todo.urn)
        )
    ).one_or_none()
    db_name, table_name, column_name, raw_type = row if row else (None, None, None, None)
    return _todo_out(
        todo,
        db_name=db_name,
        table_name=table_name,
        column_name=column_name,
        actual_type=raw_type,
    )
