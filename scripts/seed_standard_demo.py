#!/usr/bin/env python
"""灌入演示用存量字段数据并生成候选标准定义（字段统一治理 T-S3 本地验证）。

用真实业务库风格的表/字段/注释构造演示数据（参考 prod_tidb_operdb 的字段命名），
覆盖三类治理场景：无冲突同名众数推荐、同名不同型语义冲突、黑名单通用名排除。
幂等：每次运行先清空演示数据源（code=demo_operdb）范围内的行再重建。

    python scripts/seed_standard_demo.py [--db-url postgresql+asyncpg://...]
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - 注册 ORM 元数据
from app.models.knowledge import CommonColumnBlacklist, StandardField, StandardFieldItem
from app.models.metadata import ColumnMeta, DataSource, TableMeta
from app.schemas.standard_fields import ConfirmStandardFieldPayload
from app.services.standard_field import (
    attach_tag,
    confirm_standard_field,
    generate_standard_field_candidates,
)

DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:15432/datadict"
DEMO_SOURCE_CODE = "demo_operdb"
DEMO_DB = "operdb"

# (字段名, 定版类型, 逻辑类型, 标准释义, 业务标签[各业务域叫法])
PRE_CONFIRMED: list[tuple[str, str, str, str, list[str]]] = [
    ("waybill_no", "varchar(32)", "STRING", "运单编号，全局唯一", ["运单号", "提单号"]),
    ("send_site_code", "varchar(16)", "STRING", "寄件网点编号", ["寄件网点", "发货网点"]),
]

# 表名 -> [(字段名, 原始类型, 逻辑类型, 注释)]，字段命名与真实运营库一致
TABLES: dict[str, list[tuple[str, str, str, str | None]]] = {
    "cust_tab_work_order": [
        ("id", "int", "INT", "主键ID"),
        ("bill_code", "varchar(32)", "STRING", "运单号"),
        ("work_order_code", "varchar(32)", "STRING", "工单编号"),
        ("work_type", "varchar(8)", "STRING", "工单类型"),
        ("send_site_code", "varchar(16)", "STRING", "寄件网点编号"),
        ("sender_name", "varchar(64)", "STRING", "发件人姓名"),
        ("mobile", "varchar(20)", "STRING", "手机号"),
        ("status", "tinyint", "INT", "状态"),
        ("user_id", "bigint", "INT", "用户ID"),
        ("create_time", "datetime", "DATETIME", "创建时间"),
    ],
    "cust_waybill_evaluate": [
        ("id", "bigint", "INT", "主键ID"),
        ("bill_code", "varchar(32)", "STRING", "运单号"),
        ("waybill_no", "varchar(32)", "STRING", "运单编号"),
        ("send_site_code", "varchar(16)", "STRING", "寄件网点编号"),
        ("mobile", "varchar(20)", "STRING", "手机号"),
        ("user_id", "bigint", "INT", "用户ID"),
        ("create_time", "datetime", "DATETIME", "创建时间"),
    ],
    "tab_exception": [
        ("id", "bigint", "INT", "主键ID"),
        ("bill_code", "varchar(32)", "STRING", "运单号"),
        ("waybill_no", "varchar(32)", "STRING", "运单编号"),
        ("send_site_code", "bigint", "INT", "寄件网点"),  # 语义级冲突：同名不同类型
        ("site_code", "varchar(16)", "STRING", "网点编号"),
        ("remark", "varchar(255)", "STRING", "备注"),
    ],
    "common_sms_send_record": [
        ("id", "bigint", "INT", "主键ID"),
        ("waybill_no", "varchar(32)", "STRING", "运单编号"),
        ("mobile", "varchar(11)", "STRING", "手机号码"),  # 长度不一致，众数推荐
        ("send_site_code", "varchar(16)", "STRING", "寄件网点编号"),
        ("create_time", "datetime", "DATETIME", "创建时间"),
    ],
    "orders": [
        ("id", "bigint", "INT", "主键ID"),
        ("order_no", "varchar(32)", "STRING", "订单编号"),
        ("waybill_no", "varchar(32)", "STRING", "运单编号"),
        ("mobile", "varchar(20)", "STRING", "手机号"),
        ("sender_name", "varchar(64)", "STRING", "发件人姓名"),
        ("user_id", "bigint", "INT", "用户ID"),
        ("pay_amount", "decimal(12,2)", "DECIMAL", "支付金额"),
        ("status", "tinyint", "INT", "订单状态"),
    ],
    "waybill_main_detail": [
        ("id", "bigint", "INT", "主键ID"),
        ("waybill_no", "varchar(32)", "STRING", "运单编号"),
        ("bill_code", "varchar(32)", "STRING", "运单号"),
        ("site_code", "varchar(16)", "STRING", "网点编号"),
        ("sender_name", "varchar(64)", "STRING", "发件人姓名"),
        ("work_type", "tinyint", "INT", "工单类型"),  # 与 varchar(8) 构成冲突
    ],
    "basic_site": [
        ("id", "bigint", "INT", "主键ID"),
        ("site_code", "varchar(16)", "STRING", "网点编号"),
        ("site_name", "varchar(64)", "STRING", "网点名称"),
        ("site_type_code", "varchar(8)", "STRING", "网点类型"),
        ("mobile", "varchar(20)", "STRING", "联系电话"),
        ("user_id", "bigint", "INT", "负责人用户ID"),
    ],
    "k13_tab_pic_scan": [
        ("id", "bigint", "INT", "主键ID"),
        ("bill_code", "varchar(32)", "STRING", "运单编号"),
        ("waybill_no", "varchar(32)", "STRING", "运单编号"),
        ("site_code", "varchar(16)", "STRING", "网点编号"),
        ("create_time", "datetime", "DATETIME", "扫描时间"),
    ],
}

BLACKLIST = ["status", "type", "name", "code", "remark"]


async def seed(db_url: str) -> None:
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        async with session.begin():
            # 清理演示范围（标准定义全清，演示库按 字段→表→数据源 顺序重建）
            await session.execute(delete(StandardFieldItem))
            await session.execute(delete(StandardField))
            demo_source_ids = (
                (
                    await session.execute(
                        select(DataSource.id).where(DataSource.code == DEMO_SOURCE_CODE)
                    )
                )
                .scalars()
                .all()
            )
            if demo_source_ids:
                urns = (
                    (
                        await session.execute(
                            select(TableMeta.urn).where(TableMeta.source_id.in_(demo_source_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
                if urns:
                    await session.execute(delete(ColumnMeta).where(ColumnMeta.table_urn.in_(urns)))
                await session.execute(
                    delete(TableMeta).where(TableMeta.source_id.in_(demo_source_ids))
                )
                await session.execute(delete(DataSource).where(DataSource.id.in_(demo_source_ids)))
            for name in BLACKLIST:
                stmt = pg_insert(CommonColumnBlacklist).values(
                    column_name=name, reason="通用字段名，同名不同义风险高"
                )
                await session.execute(stmt.on_conflict_do_nothing(index_elements=["column_name"]))

            source = DataSource(
                code=DEMO_SOURCE_CODE,
                name="运营库（演示）",
                db_type="mysql",
                env="prod",
                host="demo.internal",
                port=3306,
                default_db=DEMO_DB,
                username="demo",
                password_cipher="demo-not-a-real-credential",  # noqa: S106 - 演示占位，非真实凭证
            )
            session.add(source)
            await session.flush()

            ordinal_base = 0
            for table_name, columns in TABLES.items():
                table_urn = f"mysql:{DEMO_SOURCE_CODE}:{DEMO_DB}:{table_name}"
                session.add(
                    TableMeta(
                        urn=table_urn,
                        source_id=source.id,
                        db_name=DEMO_DB,
                        table_name=table_name,
                        table_comment=f"{table_name} 演示表",
                    )
                )
                for i, (col_name, raw_type, logical_type, comment) in enumerate(columns, 1):
                    session.add(
                        ColumnMeta(
                            urn=f"{table_urn}:{col_name}",
                            table_urn=table_urn,
                            column_name=col_name,
                            ordinal=i,
                            raw_type=raw_type,
                            logical_type=logical_type,
                            raw_comment=comment,
                            is_primary_key=col_name == "id",
                        )
                    )
                    ordinal_base += 1

        summary = await generate_standard_field_candidates(session)

        # 演示状态：定版两个标准并打业务标签（不同业务域的叫法）
        for name, raw_type, logical_type, meaning, tags in PRE_CONFIRMED:
            sf = (
                await session.execute(
                    select(StandardField).where(StandardField.standard_name == name)
                )
            ).scalar_one_or_none()
            if sf is not None and sf.status == "DRAFT":
                await confirm_standard_field(
                    session,
                    sf.id,
                    ConfirmStandardFieldPayload(
                        raw_type=raw_type,
                        logical_type=logical_type,
                        business_meaning=meaning,
                    ),
                )
                for tag in tags:
                    await attach_tag(session, sf.id, tag)

        await session.commit()

    print(f"seeded columns: {ordinal_base}")
    print(
        f"clustering: generated={summary.generated} updated={summary.updated} "
        f"skipped_confirmed={summary.skipped_confirmed} skipped_conflict={summary.skipped_conflict}"
    )
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-url", default=DEFAULT_DB_URL)
    args = parser.parse_args()
    asyncio.run(seed(args.db_url))


if __name__ == "__main__":
    main()
