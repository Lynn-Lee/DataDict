"""基础查询接口（DEV-TASKS T6.2）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.db.session import get_web_session
from app.schemas.metadata_queries import (
    ChangeOut,
    ColumnOut,
    DataSourceOut,
    MetadataPage,
    SearchOut,
    TableDdlOut,
    TableOut,
)
from app.schemas.urns import ColumnUrn, TableUrn
from app.services.metadata_queries import MetadataQuerySession, SQLAlchemyMetadataQueryService

router = APIRouter(tags=["metadata"])


def get_metadata_query_service() -> SQLAlchemyMetadataQueryService:
    return SQLAlchemyMetadataQueryService()


@router.get(
    "/datasources",
    response_model=MetadataPage[DataSourceOut],
    summary="数据源列表",
    description="分页返回已登记的数据源基础信息，用于搜索页筛选与表详情头部展示。",
)
async def list_data_sources(
    session: Annotated[MetadataQuerySession, Depends(get_web_session)],
    service: Annotated[SQLAlchemyMetadataQueryService, Depends(get_metadata_query_service)],
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始", examples=[1])] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页数量", examples=[20])] = 20,
) -> MetadataPage[DataSourceOut]:
    return await service.list_data_sources(session, page=page, page_size=page_size)


@router.get(
    "/tables",
    response_model=MetadataPage[TableOut],
    summary="表列表或表详情",
    description=(
        "不传 urn 时分页返回表列表，可按数据源、库名和关键词筛选；"
        "传入表 URN 时返回该表详情。URN 一律通过 query 参数传递。"
    ),
)
async def list_tables(
    session: Annotated[MetadataQuerySession, Depends(get_web_session)],
    service: Annotated[SQLAlchemyMetadataQueryService, Depends(get_metadata_query_service)],
    urn: Annotated[
        TableUrn | None,
        Query(description="表 URN，传入时返回单表详情", examples=["mysql:crm:sales:orders"]),
    ] = None,
    source_id: Annotated[int | None, Query(ge=1, description="数据源 ID", examples=[1])] = None,
    db_name: Annotated[str | None, Query(description="库名", examples=["sales"])] = None,
    keyword: Annotated[
        str | None, Query(description="表名或表注释关键词", examples=["订单"])
    ] = None,
    include_deleted: Annotated[
        bool,
        Query(description="是否包含已软删除表", examples=[False]),
    ] = False,
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始", examples=[1])] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页数量", examples=[20])] = 20,
) -> MetadataPage[TableOut]:
    return await service.list_tables(
        session,
        urn=urn,
        source_id=source_id,
        db_name=db_name,
        keyword=keyword,
        include_deleted=include_deleted,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/columns",
    response_model=MetadataPage[ColumnOut],
    summary="字段列表或字段详情",
    description=(
        "传 table_urn 时分页返回表内字段；传字段 urn 时返回字段详情。"
        "响应基于 v_column_effective 暴露字段有效业务语义。"
    ),
)
async def list_columns(
    session: Annotated[MetadataQuerySession, Depends(get_web_session)],
    service: Annotated[SQLAlchemyMetadataQueryService, Depends(get_metadata_query_service)],
    urn: Annotated[
        ColumnUrn | None,
        Query(
            description="字段 URN，传入时返回单字段详情",
            examples=["mysql:crm:sales:orders:pay_amount"],
        ),
    ] = None,
    table_urn: Annotated[
        TableUrn | None,
        Query(description="表 URN，传入时返回该表字段列表", examples=["mysql:crm:sales:orders"]),
    ] = None,
    keyword: Annotated[
        str | None, Query(description="字段名或字段注释关键词", examples=["金额"])
    ] = None,
    include_deleted: Annotated[
        bool,
        Query(description="是否包含已软删除字段", examples=[False]),
    ] = False,
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始", examples=[1])] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页数量", examples=[20])] = 20,
) -> MetadataPage[ColumnOut]:
    return await service.list_columns(
        session,
        urn=urn,
        table_urn=table_urn,
        keyword=keyword,
        include_deleted=include_deleted,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/tables/ddl",
    response_model=TableDdlOut,
    summary="表 DDL",
    description="根据表 URN 生成可复制的建表 DDL，供表详情页 DDL Tab 和 API 消费方使用。",
)
async def get_table_ddl(
    session: Annotated[MetadataQuerySession, Depends(get_web_session)],
    service: Annotated[SQLAlchemyMetadataQueryService, Depends(get_metadata_query_service)],
    urn: Annotated[
        TableUrn,
        Query(description="表 URN", examples=["mysql:crm:sales:orders"]),
    ],
) -> TableDdlOut:
    return await service.get_table_ddl(session, urn=urn)


@router.get(
    "/search",
    response_model=SearchOut,
    summary="全文检索",
    description=(
        "同时检索表名、表注释、字段名、字段注释与人工业务语义，返回表命中和按表分组的字段命中结果。"
    ),
)
async def search(
    session: Annotated[MetadataQuerySession, Depends(get_web_session)],
    service: Annotated[SQLAlchemyMetadataQueryService, Depends(get_metadata_query_service)],
    q: Annotated[
        str,
        Query(min_length=2, max_length=128, description="搜索关键词", examples=["订单"]),
    ],
    page: Annotated[int, Query(ge=1, description="页码，从 1 开始", examples=[1])] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页数量", examples=[20])] = 20,
) -> SearchOut:
    return await service.search(session, query=q, page=page, page_size=page_size)


@router.get(
    "/changes",
    response_model=MetadataPage[ChangeOut],
    summary="结构变更记录",
    description=(
        "变更流水（PRD M3/M9）：表新增/删除、字段新增/删除、类型变更、注释变更、索引变更。"
        "按 table_urn 查整表时间线，或按 urn 查单字段历史；时间倒序分页。"
    ),
)
async def list_changes(
    session: Annotated[MetadataQuerySession, Depends(get_web_session)],
    service: Annotated[SQLAlchemyMetadataQueryService, Depends(get_metadata_query_service)],
    table_urn: Annotated[
        TableUrn | None,
        Query(description="表 URN，查该表的整表变更时间线"),
    ] = None,
    urn: Annotated[
        ColumnUrn | None,
        Query(description="字段 URN，查单字段变更历史"),
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> MetadataPage[ChangeOut]:
    return await service.list_changes(
        session, table_urn=table_urn, urn=urn, page=page, page_size=page_size
    )
