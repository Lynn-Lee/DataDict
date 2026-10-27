from collections import defaultdict

from app.services.excel_import import (
    ExcelColumnDoc,
    parse_dict_sheet,
    parse_table_sheet,
    parse_table_sheet_banded,
    parse_workbook,
)

# 真实 Excel 的两种表块起始版式
_TABLE_ROW_WITH_LABEL = ["表名", "tx_oper_center", None, "表名描述", "分拨到港", None]
_TABLE_ROW_NO_LABEL = [None, None, "tx_basic_dict_entry", "表名描述", None, "数据字典实例表"]
_HEADER_A = ["列序号", "字段描述", "列名", "字段类型", "默认值", "约束", "备注"]
_HEADER_B = ["序号", "字段描述", "字段", "字段类型", "默认值", "约束", "备注", "最后更新时间"]


def test_parse_table_sheet_handles_both_header_variants():
    rows = [
        _TABLE_ROW_WITH_LABEL,
        _HEADER_A,
        [1, "分拨到港id", "center_arrive_id", "bigint", None, "PK", None],
        [2, "实物条码号码", "scan_waybill_no", "varchar(32)", None, "not null", "运单子单号"],
    ]

    docs = parse_table_sheet(rows)

    assert docs == [
        ExcelColumnDoc(
            table_name="tx_oper_center",
            table_desc="分拨到港",
            column_name="center_arrive_id",
            column_desc="分拨到港id",
            column_type="bigint",
            remark=None,
        ),
        ExcelColumnDoc(
            table_name="tx_oper_center",
            table_desc="分拨到港",
            column_name="scan_waybill_no",
            column_desc="实物条码号码",
            column_type="varchar(32)",
            remark="运单子单号",
        ),
    ]


def test_parse_table_sheet_multiple_blocks_and_no_label_variant():
    rows = [
        _TABLE_ROW_NO_LABEL,
        _HEADER_B,
        [1, "网点编号", "site_code", "varchar(16)", None, "主键", None, None],
        ["说明：本模块含多张表", None, None, None, None, None, None, None],
        _TABLE_ROW_WITH_LABEL,
        _HEADER_A,
        [1, "运单主单号", "waybill_no", "varchar(16)", None, "not null", None],
    ]

    docs = parse_table_sheet(rows)

    assert [(d.table_name, d.column_name) for d in docs] == [
        ("tx_basic_dict_entry", "site_code"),
        ("tx_oper_center", "waybill_no"),
    ]
    assert docs[0].table_desc == "数据字典实例表"


def test_parse_table_sheet_skips_non_identifier_rows():
    rows = [
        _TABLE_ROW_WITH_LABEL,
        _HEADER_A,
        [1, "正常字段", "task_no", "varchar(128)", None, "not null", None],
        [None, "这一行是说明文字", "待定，需要业务确认", None, None, None, None],
    ]

    docs = parse_table_sheet(rows)

    assert [d.column_name for d in docs] == ["task_no"]


def test_parse_table_sheet_takes_name_not_serial_before_label():
    # 真实版式：表名前有序号和「表名称」标签，取第一个非空会抓到序号
    rows = [
        ["1", "表名称", "tx_order_info", "表名描述", "订单表", None],
        _HEADER_A,
        [1, "订单编号", "order_no", "varchar(32)", None, "not null", None],
    ]

    docs = parse_table_sheet(rows)

    assert docs[0].table_name == "tx_order_info"
    assert docs[0].table_desc == "订单表"


def test_parse_banded_sheet_splits_side_by_side_blocks():
    # crm sheet 版式：左带（列 0-4）与右带（列 5-11）并排各自的表块
    left_header = ["序号", "字段描述", "列名", "字段类型", "默认值", None, None]
    rows = [
        ["表名", "crm_visit", None, "表名描述", "拜访信息表", None, None],
        left_header,
        ["1", "拜访ID", "visit_id", "bigint", None, None, None],
        ["2", "网点名称", "site_name", "varchar(32)", "YES", None, None],
        [
            None,
            None,
            None,
            None,
            None,
            "拆单明细表",
            "crm_bill_split_detail",
            "表名描述",
            "数据字典实例表",
            None,
            None,
            None,
        ],
        [
            "3",
            "负责人",
            "manage_name",
            "varchar(32)",
            "YES",
            "序号",
            "字段描述",
            "列名",
            "字段类型",
            "默认值",
            "约束",
            "备注",
        ],
        [None, None, None, None, None, "1", "主键", "cid", "varchar(32)", "NO", "PRI", None],
        [None, None, None, None, None, "2", "运单号", "ewb_no", "varchar(30)", "NO", "MUL", None],
    ]

    docs = parse_table_sheet_banded(rows)

    by_table = defaultdict(list)
    for doc in docs:
        by_table[doc.table_name].append(doc.column_name)
    assert by_table["crm_visit"] == ["visit_id", "site_name", "manage_name"]
    assert by_table["crm_bill_split_detail"] == ["cid", "ewb_no"]


def test_parse_dict_sheet_groups_by_type_code():
    rows = [
        ["序号", "type_code", "type_name", "dict_code", "dict_name", "parent_dict_code", "备注"],
        [1, "site_type_code", "网点类型", "900900", "总部", None, None],
        [2, "site_type_code", "网点类型", "900800", "省区", None, None],
        [3, "waybill_type", "运单类型", "10", "普通", None, None],
        [None, None, None, None, None, None, None],
    ]

    dicts = parse_dict_sheet(rows)

    assert [(d.code, d.name, len(d.items)) for d in dicts] == [
        ("site_type_code", "网点类型", 2),
        ("waybill_type", "运单类型", 1),
    ]
    assert dicts[0].items[0] == {"value": "900900", "label": "总部"}


def test_parse_dict_sheet_keeps_parent_reference():
    rows = [
        ["type_code", "type_name", "dict_code", "dict_name", "parent_dict_code"],
        ["area_code", "片区", "900601", "东区", "900600"],
    ]

    dicts = parse_dict_sheet(rows)

    assert dicts[0].items == [{"value": "900601", "label": "东区", "parent": "900600"}]


def test_parse_workbook_dispatches_dict_and_table_sheets():
    sheets = {
        "数据字典定义(非表结构)": [
            ["序号", "type_code", "type_name", "dict_code", "dict_name", "parent_dict_code"],
            [1, "site_type_code", "网点类型", "900900", "总部", None],
        ],
        "2.网点信息": [
            _TABLE_ROW_NO_LABEL,
            _HEADER_B,
            [1, "网点编号", "site_code", "varchar(16)", None, "主键", None, None],
        ],
    }

    parsed = parse_workbook(sheets)

    assert len(parsed.dicts) == 1
    assert [(d.table_name, d.column_name) for d in parsed.columns] == [
        ("tx_basic_dict_entry", "site_code")
    ]
