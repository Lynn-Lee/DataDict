"""标准字段定义接口（字段统一治理 T-S3）。

- POST /standard-fields/generate   按字段名聚类生成/刷新候选（管理员动作，幂等可重跑）
- GET  /standard-fields            候选与定版列表（status/q 筛选，分页）
- POST /standard-fields/{id}/confirm 人工确认定版（冲突项必须显式给出裁决类型）
- GET  /standard-fields/{id}       详情 + 存量源字段清单（conforms 回算结果）
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_web_session
from app.schemas.metadata_queries import MetadataPage
from app.schemas.standard_fields import (
    AttachTagPayload,
    ConfirmStandardFieldPayload,
    GenerateCandidatesOut,
    StandardFieldDetailOut,
    StandardFieldLibraryOut,
    StandardFieldOut,
    StandardFieldTagOut,
)
from app.services import standard_field as service

router = APIRouter(prefix="/standard-fields", tags=["standard-fields"])


@router.post(
    "/generate",
    response_model=GenerateCandidatesOut,
    summary="生成候选标准定义",
    description=(
        "对全库未删除字段按字段名聚类，生成或刷新 DRAFT 候选标准定义。"
        "幂等可重跑：已 CONFIRMED 的同名标准不会被覆盖；黑名单字段名自动排除。"
    ),
)
async def generate_candidates(
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> GenerateCandidatesOut:
    summary = await service.generate_standard_field_candidates(session)
    await session.commit()
    return GenerateCandidatesOut(
        generated=summary.generated,
        updated=summary.updated,
        skipped_confirmed=summary.skipped_confirmed,
        skipped_conflict=summary.skipped_conflict,
    )


@router.get(
    "",
    response_model=MetadataPage[StandardFieldOut],
    summary="标准字段定义列表",
    description=(
        "候选与定版标准定义列表。status=DRAFT 为待确认候选，CONFIRMED 为已定版；"
        "q 按字段名或业务释义模糊匹配。"
    ),
)
async def list_standard_fields(
    session: Annotated[AsyncSession, Depends(get_web_session)],
    status: Annotated[
        str | None,
        Query(description="按状态筛选", examples=["DRAFT", "CONFIRMED"]),
    ] = None,
    conflict: Annotated[
        bool | None,
        Query(description="仅看类型冲突待裁决的候选"),
    ] = None,
    q: Annotated[str | None, Query(max_length=128, description="字段名/释义关键词")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> MetadataPage[StandardFieldOut]:
    total, items = await service.list_standard_fields(
        session,
        status_filter=status,
        conflict_only=bool(conflict),
        q=q,
        page=page,
        page_size=page_size,
    )
    return MetadataPage(total=total, page=page, page_size=page_size, items=items)


@router.post(
    "/{standard_id}/confirm",
    response_model=StandardFieldOut,
    summary="确认定版标准定义",
    description=(
        "人工确认候选为标准定义：标准字段名、类型（含长度）、逻辑类型、释义均可修改，"
        "状态 DRAFT→CONFIRMED，并按「字段名 + 类型都一致」回算组内存量字段的 conforms。"
        "冲突候选必须显式给出裁决后的 raw_type/logical_type。"
        "若改名后与库中已有活跃标准重名，返回 409 并给出该标准，应改走 merge-into 关联，"
        "避免标准库出现两个同义标准。"
    ),
)
async def confirm_standard_field(
    standard_id: int,
    payload: ConfirmStandardFieldPayload,
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> StandardFieldOut:
    out = await service.confirm_standard_field(session, standard_id, payload)
    await session.commit()
    return out


@router.get(
    "/library",
    response_model=MetadataPage[StandardFieldLibraryOut],
    summary="终版标准定义库",
    description=(
        "已定版（CONFIRMED）的标准字段定义列表，含业务标签"
        "（同一标准释义在不同业务域的叫法）。供设计态查询与 AI/MCP 消费。"
    ),
)
async def list_standard_field_library(
    session: Annotated[AsyncSession, Depends(get_web_session)],
    q: Annotated[str | None, Query(max_length=128, description="字段名/释义关键词")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> MetadataPage[StandardFieldLibraryOut]:
    total, items = await service.list_confirmed_standards(
        session, q=q, page=page, page_size=page_size
    )
    return MetadataPage(total=total, page=page, page_size=page_size, items=items)


@router.get(
    "/tag-options",
    response_model=list[str],
    summary="业务标签候选",
    description="已有业务别名标签名列表，供前端自动补全。",
)
async def list_standard_field_tag_options(
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> list[str]:
    return await service.list_tag_options(session)


@router.post(
    "/{standard_id}/tags",
    response_model=list[StandardFieldTagOut],
    summary="添加业务标签",
    description="给标准定义打业务标签（不同业务域的叫法）；标签不存在时自动创建。",
)
async def attach_standard_field_tag(
    standard_id: int,
    payload: AttachTagPayload,
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> list[StandardFieldTagOut]:
    tags = await service.attach_tag(session, standard_id, payload.name)
    await session.commit()
    return tags


@router.delete(
    "/{standard_id}/tags/{tag_id}",
    response_model=list[StandardFieldTagOut],
    summary="移除业务标签",
)
async def detach_standard_field_tag(
    standard_id: int,
    tag_id: int,
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> list[StandardFieldTagOut]:
    tags = await service.detach_tag(session, standard_id, tag_id)
    await session.commit()
    return tags


@router.post(
    "/{standard_id}/merge-into/{target_id}",
    response_model=StandardFieldOut,
    summary="关联（合并）到已有标准",
    description=(
        "候选与标准库中已有条目是同一概念时使用：存量字段关联迁到目标下并按"
        "「名 + 型」重算 conforms，候选置 MERGED，来源字段名记为目标的业务别名"
        "（后续同步可据此拦截新增的异名违规字段）。标准库因此不会出现两个同义标准。"
        "目标可以是已定版标准，也可以是另一个待确认候选（同义候选先归并再一起定版）。"
    ),
)
async def merge_standard_field(
    standard_id: int,
    target_id: int,
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> StandardFieldOut:
    out = await service.merge_standard_field(session, standard_id, target_id)
    await session.commit()
    return out


@router.get(
    "/{standard_id}",
    response_model=StandardFieldDetailOut,
    summary="标准字段定义详情",
    description="定版定义 + 组内存量源字段清单（库/表/字段/原始类型/conforms）。",
)
async def get_standard_field(
    standard_id: int,
    session: Annotated[AsyncSession, Depends(get_web_session)],
) -> StandardFieldDetailOut:
    return await service.get_standard_field_detail(session, standard_id)
