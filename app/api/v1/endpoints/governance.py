"""治理接口（T-S8：同步比对拦截的处理闭环）。

- POST /governance/sweep           手动触发一次治理扫描（同步后也会自动链式执行）
- GET  /governance/todos           治理待办列表（status=OPEN 待处理 / IGNORED 含豁免清单）
- POST /governance/todos/{id}/resolve  处理待办：采纳标准 / 豁免（必须填原因）/ 忽略
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_web_session
from app.schemas.governance import GovernanceSweepOut, GovernanceTodoOut, ResolveTodoPayload
from app.schemas.metadata_queries import MetadataPage
from app.services import governance as service

router = APIRouter(prefix="/governance", tags=["governance"])


@router.post(
    "/sweep",
    response_model=GovernanceSweepOut,
    summary="触发治理扫描",
    description=(
        "把活跃字段与已定版标准比对：未挂载的挂入标准组并回算 conforms，"
        "类型不一致的生成 STANDARD_CONFLICT 待办。幂等可重跑。"
    ),
)
async def trigger_sweep(
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> GovernanceSweepOut:
    summary = await service.run_governance_sweep(session)
    await session.commit()
    return GovernanceSweepOut(
        attached_conforming=summary.attached_conforming,
        attached_conflicting=summary.attached_conflicting,
        conforms_updated=summary.conforms_updated,
        todos_created=summary.todos_created,
    )


@router.get(
    "/todos",
    response_model=MetadataPage[GovernanceTodoOut],
    summary="治理待办列表",
    description=(
        "同步比对产生的标准冲突待办。status=OPEN 为待处理；"
        "status=IGNORED 中含豁免清单（action=EXEMPT，带原因留痕）。"
    ),
)
async def list_todos(
    session: Annotated[AsyncSession, Depends(get_web_session)],
    status: Annotated[
        str | None,
        Query(description="OPEN / DONE / IGNORED；不传返回全部", examples=["OPEN"]),
    ] = "OPEN",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> MetadataPage[GovernanceTodoOut]:
    total, items = await service.list_governance_todos(
        session, status=status, page=page, page_size=page_size
    )
    return MetadataPage(total=total, page=page, page_size=page_size, items=items)


@router.post(
    "/todos/{todo_id}/resolve",
    response_model=GovernanceTodoOut,
    summary="处理治理待办",
    description="ADOPT=采纳标准；EXEMPT=豁免（必须填原因，进入豁免清单留痕）；IGNORE=忽略。",
)
async def resolve_todo(
    todo_id: int,
    payload: ResolveTodoPayload,
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> GovernanceTodoOut:
    out = await service.resolve_governance_todo(session, todo_id, payload)
    await session.commit()
    return out
