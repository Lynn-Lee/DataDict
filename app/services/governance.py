"""同步后治理联动：存量字段 × 已定版标准比对（T-S8a）。

采集流程（collector 角色）对知识层无写权限——DEV-TASKS §7 红线第 6 条。
因此比对不在同步事务内做，而是同步完成后由本服务用 web 会话执行，幂等可重跑：

- 活跃字段按字段名匹配 CONFIRMED 标准定义
- 未挂载的字段 → 挂入 standard_field_item；类型一致 conforms=true，
  不一致 conforms=false 并生成 STANDARD_CONFLICT 治理待办（当周拦截新增混乱）
- 已挂载但类型漂移的字段 → 重算 conforms，漂移为不符合时补待办
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, DataDictError, NotFoundError
from app.db.session import web_session
from app.models.knowledge import StandardField, StandardFieldItem
from app.models.metadata import ColumnMeta, TableMeta
from app.models.support import AnnotationTodo
from app.schemas.governance import GovernanceTodoOut, ResolveTodoPayload

GOVERNANCE_TODO_TYPE = "STANDARD_CONFLICT"


@dataclass
class GovernanceSweepSummary:
    attached_conforming: int = 0
    attached_conflicting: int = 0
    conforms_updated: int = 0
    todos_created: int = 0


async def run_governance_sweep(session: AsyncSession) -> GovernanceSweepSummary:
    summary = GovernanceSweepSummary()

    standards = (
        (await session.execute(select(StandardField).where(StandardField.status == "CONFIRMED")))
        .scalars()
        .all()
    )
    if not standards:
        return summary
    std_by_name = {std.standard_name: std for std in standards}

    items = (
        (
            await session.execute(
                select(StandardFieldItem).where(
                    StandardFieldItem.standard_field_id.in_([std.id for std in standards])
                )
            )
        )
        .scalars()
        .all()
    )
    item_by_urn = {item.column_urn: item for item in items}

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

    col_rows = await session.execute(
        select(ColumnMeta.urn, ColumnMeta.column_name, ColumnMeta.raw_type).where(
            ColumnMeta.is_deleted.is_(False),
            ColumnMeta.column_name.in_(list(std_by_name)),
        )
    )

    for urn, column_name, raw_type in col_rows:
        std = std_by_name[column_name]
        conforms = raw_type == std.raw_type
        item = item_by_urn.get(urn)

        if item is None:
            session.add(
                StandardFieldItem(standard_field_id=std.id, column_urn=urn, conforms=conforms)
            )
            if conforms:
                summary.attached_conforming += 1
            else:
                summary.attached_conflicting += 1
        elif item.conforms != conforms:
            item.conforms = conforms
            summary.conforms_updated += 1

        if not conforms and urn not in existing_todo_urns:
            session.add(
                AnnotationTodo(
                    urn=urn,
                    todo_type=GOVERNANCE_TODO_TYPE,
                    status="OPEN",
                    priority=1,
                    payload={
                        "standard_field_id": std.id,
                        "standard_name": std.standard_name,
                        "expected_type": std.raw_type,
                        "actual_type": raw_type,
                        "business_meaning": std.business_meaning,
                    },
                )
            )
            existing_todo_urns.add(urn)
            summary.todos_created += 1

    await session.flush()
    return summary


async def run_governance_sweep_standalone() -> GovernanceSweepSummary:
    """独立执行一次治理扫描（自开 web 会话），供调度 job 与同步后链式调用。"""
    async with web_session() as session:
        summary = await run_governance_sweep(session)
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
    return GovernanceTodoOut(
        id=todo.id,
        column_urn=todo.urn,
        db_name=db_name,
        table_name=table_name,
        column_name=column_name,
        actual_type=actual_type,
        standard_field_id=payload.get("standard_field_id"),
        standard_name=payload.get("standard_name"),
        expected_type=payload.get("expected_type"),
        business_meaning=payload.get("business_meaning"),
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
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[GovernanceTodoOut]]:
    stmt = (
        select(
            AnnotationTodo,
            TableMeta.db_name,
            TableMeta.table_name,
            ColumnMeta.column_name,
            ColumnMeta.raw_type,
        )
        .join(ColumnMeta, ColumnMeta.urn == AnnotationTodo.urn)
        .join(TableMeta, TableMeta.urn == ColumnMeta.table_urn)
        .where(AnnotationTodo.todo_type == GOVERNANCE_TODO_TYPE)
    )
    if status:
        stmt = stmt.where(AnnotationTodo.status == status)

    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(AnnotationTodo)
                .where(
                    AnnotationTodo.todo_type == GOVERNANCE_TODO_TYPE,
                    *([AnnotationTodo.status == status] if status else []),
                )
            )
        ).scalar_one()
    )
    rows = await session.execute(
        stmt.order_by(AnnotationTodo.created_at.desc(), AnnotationTodo.id.desc())
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
    if todo is None or todo.todo_type != GOVERNANCE_TODO_TYPE:
        raise NotFoundError("治理待办不存在", detail={"id": todo_id})
    if todo.status != "OPEN":
        raise ConflictError("该待办已处理", detail={"status": todo.status})
    if payload.action == "EXEMPT" and not (payload.reason or "").strip():
        raise DataDictError("豁免必须填写原因（留痕，供治理复盘）")

    todo.status = "DONE" if payload.action == "ADOPT" else "IGNORED"
    todo.done_at = datetime.now(UTC)
    todo.payload = {
        **(todo.payload or {}),
        "action": payload.action,
        "reason": (payload.reason or "").strip() or None,
    }
    await session.flush()

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
